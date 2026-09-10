from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from finance.models import CustomerLedgerEntry
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine, InventoryBatch, PartInventory
from operations.services import (
    apply_container_inventory_delta,
    available_quantity_for_batch,
    available_quantity_for_item,
    create_auction_sale,
    create_subparts,
    issue_gate_pass,
    is_container_cost_locked,
    net_unit_cost_for_batch,
    price_locked_quantity_merge,
    price_new_locked_container_item,
    recalculate_container_net_costs,
    sold_quantity_for_item,
    sold_quantity_for_batch,
    update_auction_sale,
    update_gate_pass,
)


class CustomerSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    customer_type = serializers.ChoiceField(choices=Customer.CustomerType.choices, required=False, default=Customer.CustomerType.INDIVIDUAL)
    opening_balance = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.00'), required=False, write_only=True, default=Decimal('0.00'))
    opening_balance_direction = serializers.ChoiceField(
        choices=[('receivable', 'Customer owes ZSP'), ('credit', 'Customer has advance/credit')],
        required=False,
        write_only=True,
        default='receivable',
    )

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'customer_type', 'phone', 'email', 'cnic_or_tax_id',
            'address', 'notes', 'is_active', 'balance', 'can_delete', 'created_at', 'updated_at',
            'opening_balance', 'opening_balance_direction',
        ]
        read_only_fields = ['id', 'balance', 'can_delete', 'created_at', 'updated_at']

    @transaction.atomic
    def create(self, validated_data):
        opening_balance = validated_data.pop('opening_balance', Decimal('0.00')) or Decimal('0.00')
        opening_balance_direction = validated_data.pop('opening_balance_direction', 'receivable')
        customer = super().create(validated_data)
        if opening_balance > 0:
            user = self.context['request'].user
            CustomerLedgerEntry.objects.create(
                customer=customer,
                entry_date=timezone.localdate(),
                entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
                description='Opening balance',
                debit=opening_balance if opening_balance_direction == 'receivable' else Decimal('0.00'),
                credit=opening_balance if opening_balance_direction == 'credit' else Decimal('0.00'),
                created_by=user,
                updated_by=user,
            )
        return customer

    def update(self, instance, validated_data):
        validated_data.pop('opening_balance', None)
        validated_data.pop('opening_balance_direction', None)
        return super().update(instance, validated_data)

    def get_balance(self, obj):
        if hasattr(obj, 'ledger_debit') and hasattr(obj, 'ledger_credit'):
            return obj.ledger_debit - obj.ledger_credit
        totals = obj.ledger_entries.aggregate(debit=Sum('debit'), credit=Sum('credit'))
        return (totals['debit'] or 0) - (totals['credit'] or 0)

    def get_can_delete(self, obj):
        if all(hasattr(obj, attr) for attr in ['auction_sale_count', 'cheque_count', 'ledger_entry_count']):
            return obj.auction_sale_count == 0 and obj.cheque_count == 0 and obj.ledger_entry_count == 0
        return not obj.auction_sales.exists() and not obj.cheques.exists() and not obj.ledger_entries.exists()

    def validate_phone(self, value):
        if not value.startswith('+') or len(value) < 8:
            raise serializers.ValidationError('Phone number must include a country code, for example +923001234567.')
        return value


class ContainerSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, default=0)
    raw_parts_cost = serializers.SerializerMethodField()
    total_container_cost = serializers.SerializerMethodField()

    class Meta:
        model = Container
        fields = [
            'id', 'reference', 'origin_country', 'supplier_name', 'arrival_date',
            'manifest_notes', 'status', 'added_cost', 'item_count',
            'raw_parts_cost', 'total_container_cost', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'item_count', 'raw_parts_cost', 'total_container_cost', 'created_at', 'updated_at']

    def get_raw_parts_cost(self, obj):
        if hasattr(obj, 'raw_parts_cost_total'):
            return obj.raw_parts_cost_total or Decimal('0.00')
        return sum((item.raw_unit_cost * item.quantity for item in obj.items.all()), Decimal('0.00'))

    def get_total_container_cost(self, obj):
        return self.get_raw_parts_cost(obj) + (obj.added_cost or Decimal('0.00'))

    def create(self, validated_data):
        instance = super().create(validated_data)
        return instance

    def update(self, instance, validated_data):
        previous_status = instance.status
        instance = super().update(instance, validated_data)
        moved_to_recalculating_state = previous_status in {Container.Status.READY_FOR_AUCTION, Container.Status.CLOSED} and not is_container_cost_locked(instance)
        cost_sensitive_change = 'added_cost' in validated_data or 'status' in validated_data
        if cost_sensitive_change and (not is_container_cost_locked(instance) or moved_to_recalculating_state):
            recalculate_container_net_costs(user=self.context['request'].user, container=instance)
        return instance


class ContainerItemSerializer(serializers.ModelSerializer):
    container_reference = serializers.CharField(source='container.reference', read_only=True)
    raw_total_cost = serializers.SerializerMethodField()
    added_cost_share = serializers.SerializerMethodField()
    net_unit_cost = serializers.SerializerMethodField()
    net_total_cost = serializers.SerializerMethodField()
    has_subparts = serializers.SerializerMethodField()
    subpart_count = serializers.SerializerMethodField()

    class Meta:
        model = ContainerItem
        fields = [
            'id', 'container', 'container_reference', 'parent_item', 'lot_number', 'part_name',
            'part_number', 'description', 'category', 'quantity',
            'unit', 'raw_unit_cost', 'raw_total_cost',
            'added_cost_share', 'net_unit_cost', 'net_total_cost', 'status',
            'has_subparts', 'subpart_count', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'container_reference', 'parent_item', 'status', 'net_unit_cost',
            'has_subparts', 'subpart_count',
            'created_at', 'updated_at',
        ]

    def get_raw_total_cost(self, obj):
        return obj.raw_unit_cost * obj.quantity

    def get_added_cost_share(self, obj):
        return self.get_net_total_cost(obj) - self.get_raw_total_cost(obj)

    def get_net_total_cost(self, obj):
        return obj.net_unit_cost * obj.quantity

    def get_net_unit_cost(self, obj):
        return obj.net_unit_cost

    def get_has_subparts(self, obj):
        subpart_count = getattr(obj, 'subpart_count_total', None)
        if subpart_count is not None:
            return subpart_count > 0
        return obj.subparts.exists()

    def get_subpart_count(self, obj):
        if hasattr(obj, 'subpart_count_total'):
            return obj.subpart_count_total
        return obj.subparts.count()

    def _persist_options(self, validated_data):
        user = self.context['request'].user
        ensure_dropdown_option(group=DropdownOption.Group.PART_NAME, label=validated_data.get('part_name', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CATEGORY, label=validated_data.get('category', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_UNIT, label=validated_data.get('unit', ''), user=user)

    def _snapshot(self, instance):
        return {
            'container_item_id': instance.id,
            'part_name': instance.part_name,
            'part_number': instance.part_number or '',
            'category': instance.category or '',
            'unit': instance.unit or 'piece',
            'quantity': instance.quantity,
            'raw_unit_cost': instance.raw_unit_cost,
            'net_unit_cost': instance.net_unit_cost,
            'description': instance.description or '',
        }

    def create(self, validated_data):
        self._persist_options(validated_data)
        with transaction.atomic():
            existing = (
                ContainerItem.objects
                .select_for_update()
                .filter(
                    container=validated_data['container'],
                    part_name=validated_data['part_name'],
                    part_number=validated_data.get('part_number', '') or '',
                    category=validated_data.get('category', '') or '',
                    unit=validated_data.get('unit', 'piece') or 'piece',
                    parent_item__isnull=True,
                )
                .order_by('created_at')
                .first()
            )
            if existing is not None:
                before = self._snapshot(existing)
                old_quantity = existing.quantity
                old_net_unit_cost = existing.net_unit_cost
                incoming_quantity = validated_data.get('quantity') or 1
                next_quantity = old_quantity + incoming_quantity
                incoming_raw_unit_cost = validated_data.get('raw_unit_cost', existing.raw_unit_cost)
                weighted_raw_total = (existing.raw_unit_cost * old_quantity) + (incoming_raw_unit_cost * incoming_quantity)
                existing.quantity = next_quantity
                existing.raw_unit_cost = weighted_raw_total / next_quantity
                if validated_data.get('description'):
                    existing.description = validated_data.get('description', '')
                if is_container_cost_locked(existing.container):
                    price_locked_quantity_merge(
                        container_item=existing,
                        old_quantity=old_quantity,
                        old_net_unit_cost=old_net_unit_cost,
                        incoming_quantity=incoming_quantity,
                        incoming_raw_unit_cost=incoming_raw_unit_cost,
                    )
                existing.updated_by = self.context['request'].user
                existing.save(update_fields=[
                    'quantity', 'raw_unit_cost', 'net_unit_cost', 'description',
                    'updated_by', 'updated_at',
                ])
                apply_container_inventory_delta(user=self.context['request'].user, before=before, after=existing)
                if not is_container_cost_locked(existing.container):
                    recalculate_container_net_costs(user=self.context['request'].user, container=existing.container)
                    existing.refresh_from_db()
                return existing
            instance = super().create(validated_data)
            if is_container_cost_locked(instance.container):
                price_new_locked_container_item(instance)
                instance.save(update_fields=['net_unit_cost'])
            apply_container_inventory_delta(user=self.context['request'].user, after=instance)
            if not is_container_cost_locked(instance.container):
                recalculate_container_net_costs(user=self.context['request'].user, container=instance.container)
                instance.refresh_from_db()
            return instance


class SubpartWriteSerializer(serializers.Serializer):
    part_name = serializers.CharField(max_length=180)
    part_number = serializers.CharField(max_length=120, required=False, allow_blank=True)
    category = serializers.CharField(max_length=120, required=False, allow_blank=True)
    quantity = serializers.IntegerField(min_value=1)
    unit = serializers.CharField(max_length=30, default='piece')
    raw_unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.00'))
    description = serializers.CharField(required=False, allow_blank=True)


class SubpartCreateSerializer(serializers.Serializer):
    split_quantity = serializers.IntegerField(min_value=1)
    subparts = SubpartWriteSerializer(many=True)

    def create(self, validated_data):
        return create_subparts(
            user=self.context['request'].user,
            parent_item=self.context['parent_item'],
            **validated_data,
        )

    def to_representation(self, instance):
        return ContainerItemSerializer(instance, many=True, context=self.context).data

    def update(self, instance, validated_data):
        self._persist_options(validated_data)
        with transaction.atomic():
            before = self._snapshot(instance)
            instance = super().update(instance, validated_data)
            if is_container_cost_locked(instance.container):
                instance.net_unit_cost = Decimal(instance.raw_unit_cost or 0).quantize(Decimal('0.01'))
                instance.save(update_fields=['net_unit_cost', 'updated_at'])
            apply_container_inventory_delta(user=self.context['request'].user, before=before, after=instance)
            if not is_container_cost_locked(instance.container):
                recalculate_container_net_costs(user=self.context['request'].user, container=instance.container)
                instance.refresh_from_db()
            return instance


class InventoryBatchSerializer(serializers.ModelSerializer):
    container_reference = serializers.CharField(source='container.reference', read_only=True)
    part_name = serializers.CharField(source='item.part_name', read_only=True)
    part_number = serializers.CharField(source='item.part_number', read_only=True)
    category = serializers.CharField(source='item.category', read_only=True)
    unit = serializers.CharField(source='item.unit', read_only=True)
    sold_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()
    net_unit_cost = serializers.SerializerMethodField()

    class Meta:
        model = InventoryBatch
        fields = [
            'id', 'item', 'part_name', 'part_number', 'category',
            'unit', 'container', 'container_reference', 'container_item',
            'source_label', 'quantity', 'sold_quantity', 'available_quantity',
            'raw_unit_cost', 'net_unit_cost', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_sold_quantity(self, obj):
        if hasattr(obj, 'sold_quantity_total'):
            return obj.sold_quantity_total
        return sold_quantity_for_batch(obj)

    def get_available_quantity(self, obj):
        sold_quantity = getattr(obj, 'sold_quantity_total', None)
        if sold_quantity is not None:
            return max(int(obj.quantity) - int(sold_quantity or 0), 0)
        return available_quantity_for_batch(obj)

    def get_net_unit_cost(self, obj):
        return f'{net_unit_cost_for_batch(obj):.2f}'


class PartInventorySourceWriteSerializer(serializers.Serializer):
    container = serializers.PrimaryKeyRelatedField(queryset=Container.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    raw_unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.00'))
    description = serializers.CharField(required=False, allow_blank=True)


class PartInventorySerializer(serializers.ModelSerializer):
    sold_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()
    batches = InventoryBatchSerializer(read_only=True, many=True)
    source_container = serializers.PrimaryKeyRelatedField(
        queryset=Container.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    raw_unit_cost = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        write_only=True,
        required=False,
        default=Decimal('0.00'),
        min_value=Decimal('0.00'),
    )
    sources = PartInventorySourceWriteSerializer(write_only=True, many=True, required=False)

    class Meta:
        model = PartInventory
        fields = [
            'id', 'part_name', 'part_number', 'description', 'category',
            'quantity', 'unit', 'sold_quantity',
            'available_quantity', 'batches', 'source_container',
            'raw_unit_cost', 'sources', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'sold_quantity', 'available_quantity', 'batches', 'created_at', 'updated_at']
        extra_kwargs = {'part_number': {'required': False, 'allow_blank': True}}
        validators = []

    def get_sold_quantity(self, obj):
        if hasattr(obj, 'sold_quantity_total'):
            return obj.sold_quantity_total
        return sold_quantity_for_item(obj)

    def get_available_quantity(self, obj):
        if hasattr(obj, 'sold_quantity_total'):
            return max(int(obj.quantity) - int(obj.sold_quantity_total or 0), 0)
        return available_quantity_for_item(obj)

    def _persist_options(self, validated_data):
        user = self.context['request'].user
        ensure_dropdown_option(group=DropdownOption.Group.PART_NAME, label=validated_data.get('part_name', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CATEGORY, label=validated_data.get('category', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_UNIT, label=validated_data.get('unit', ''), user=user)

    def validate(self, attrs):
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 0))
        if self.instance is not None and quantity < sold_quantity_for_item(self.instance):
            raise serializers.ValidationError({'quantity': 'Quantity cannot be lower than the quantity already sold.'})
        if self.instance is not None and 'quantity' in attrs and int(quantity) != int(self.instance.quantity):
            raise serializers.ValidationError({'quantity': 'Edit the individual source rows to change stock quantity.'})
        if self.instance is None and not attrs.get('sources') and not attrs.get('source_container'):
            raise serializers.ValidationError({'sources': 'At least one source container row is required when adding parts inventory directly.'})
        return attrs

    def create(self, validated_data):
        source_container = validated_data.pop('source_container', None)
        raw_unit_cost = validated_data.pop('raw_unit_cost', Decimal('0.00'))
        sources = validated_data.pop('sources', None)
        self._persist_options(validated_data)
        if not sources and source_container is not None:
            sources = [{
                'container': source_container,
                'quantity': validated_data.get('quantity') or 1,
                'raw_unit_cost': raw_unit_cost,
                'description': validated_data.get('description', ''),
            }]
        with transaction.atomic():
            for source in sources or []:
                item_serializer = ContainerItemSerializer(
                    data={
                        'container': str(source['container'].id),
                        'part_name': validated_data['part_name'],
                        'part_number': validated_data.get('part_number', '') or '',
                        'category': validated_data.get('category', '') or '',
                        'quantity': source['quantity'],
                        'unit': validated_data.get('unit', 'piece') or 'piece',
                        'raw_unit_cost': source['raw_unit_cost'],
                        'description': source.get('description') or validated_data.get('description', ''),
                    },
                    context=self.context,
                )
                item_serializer.is_valid(raise_exception=True)
                item_serializer.save(created_by=self.context['request'].user, updated_by=self.context['request'].user)
            instance = PartInventory.objects.select_for_update().get(
                part_name=validated_data['part_name'],
                part_number=validated_data.get('part_number', '') or '',
                category=validated_data.get('category', '') or '',
                unit=validated_data.get('unit', 'piece') or 'piece',
            )
            return instance

    def update(self, instance, validated_data):
        validated_data.pop('source_container', None)
        validated_data.pop('raw_unit_cost', None)
        validated_data.pop('sources', None)
        self._persist_options(validated_data)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            container_items = [
                batch.container_item
                for batch in instance.batches.select_related('container_item')
                if batch.container_item_id
            ]
            update_fields = ['part_name', 'part_number', 'category', 'unit', 'description', 'updated_by', 'updated_at']
            for container_item in container_items:
                container_item.part_name = instance.part_name
                container_item.part_number = instance.part_number
                container_item.category = instance.category
                container_item.unit = instance.unit
                container_item.description = instance.description
                container_item.updated_by = self.context['request'].user
                container_item.save(update_fields=update_fields)
            return instance


class AuctionSaleLineReadSerializer(serializers.ModelSerializer):
    item = serializers.SerializerMethodField()
    inventory_batch_label = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()
    current_raw_unit_cost = serializers.SerializerMethodField()
    current_net_unit_cost = serializers.SerializerMethodField()
    current_profit = serializers.SerializerMethodField()

    class Meta:
        model = AuctionSaleLine
        fields = [
            'id', 'item', 'inventory_batch', 'inventory_batch_label',
            'quantity', 'sold_price', 'raw_unit_cost_snapshot',
            'net_unit_cost_snapshot', 'current_raw_unit_cost',
            'current_net_unit_cost', 'current_profit', 'line_total', 'notes',
        ]

    def get_line_total(self, obj):
        return obj.quantity * obj.sold_price

    def get_item(self, obj):
        item = obj.item
        sold_quantity = getattr(obj, 'item_sold_quantity_total', None)
        if sold_quantity is None:
            sold_quantity = getattr(item, 'sold_quantity_total', None)
        if sold_quantity is None:
            sold_quantity = sold_quantity_for_item(item)
        return {
            'id': str(item.id),
            'part_name': item.part_name,
            'part_number': item.part_number,
            'description': item.description,
            'category': item.category,
            'quantity': item.quantity,
            'unit': item.unit,
            'sold_quantity': sold_quantity,
            'available_quantity': max(int(item.quantity) - int(sold_quantity or 0), 0),
            'created_at': item.created_at,
            'updated_at': item.updated_at,
        }

    def get_inventory_batch_label(self, obj):
        batch = obj.inventory_batch
        if batch is None:
            return ''
        source = batch.container.reference if batch.container_id else batch.source_label or 'Manual adjustment'
        return f'{obj.item.part_name} / {source}'

    def get_current_raw_unit_cost(self, obj):
        if obj.inventory_batch_id:
            return obj.inventory_batch.raw_unit_cost
        return obj.raw_unit_cost_snapshot

    def get_current_net_unit_cost(self, obj):
        if obj.inventory_batch_id:
            return net_unit_cost_for_batch(obj.inventory_batch)
        return obj.net_unit_cost_snapshot

    def get_current_profit(self, obj):
        return (obj.sold_price - Decimal(self.get_current_net_unit_cost(obj))) * obj.quantity


class AuctionSaleLineWriteSerializer(serializers.Serializer):
    inventory_batch = serializers.PrimaryKeyRelatedField(queryset=InventoryBatch.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class AuctionSaleLineUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    inventory_batch = serializers.PrimaryKeyRelatedField(queryset=InventoryBatch.objects.all(), required=False)
    quantity = serializers.IntegerField(min_value=1)
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class GatePassSaleLineReadSerializer(serializers.ModelSerializer):
    item = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = AuctionSaleLine
        fields = ['id', 'item', 'quantity', 'sold_price', 'line_total', 'notes']

    def get_line_total(self, obj):
        return obj.quantity * obj.sold_price

    def get_item(self, obj):
        item = obj.item
        return {
            'id': str(item.id),
            'part_name': item.part_name,
            'part_number': item.part_number,
            'description': item.description,
            'category': item.category,
            'quantity': item.quantity,
            'unit': item.unit,
            'sold_quantity': sold_quantity_for_item(item),
            'available_quantity': available_quantity_for_item(item),
            'created_at': item.created_at,
            'updated_at': item.updated_at,
        }


class ChequeForSaleSerializer(serializers.Serializer):
    cheque_number = serializers.CharField(max_length=80)
    name_on_cheque = serializers.CharField(max_length=180)
    bank_name = serializers.CharField(max_length=120)
    branch_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    account_title = serializers.CharField(max_length=180, required=False, allow_blank=True)
    cheque_date = serializers.DateField()
    expiry_date = serializers.DateField()
    received_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs['expiry_date'] < attrs['cheque_date']:
            raise serializers.ValidationError({'expiry_date': 'Expiry date cannot be before cheque date.'})
        return attrs


class PaymentBreakdownSerializer(serializers.Serializer):
    cash_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.00'), required=False, default=Decimal('0.00'))
    cheque_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.00'), required=False, default=Decimal('0.00'))
    credit_amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.00'), required=False, default=Decimal('0.00'))


class AuctionSaleSerializer(serializers.ModelSerializer):
    lines = AuctionSaleLineReadSerializer(read_only=True, many=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    gate_pass = serializers.SerializerMethodField()
    cheque_amount = serializers.SerializerMethodField()
    receivable_amount = serializers.SerializerMethodField()

    class Meta:
        model = AuctionSale
        fields = [
            'id', 'sale_number', 'sale_date', 'customer', 'customer_name',
            'payment_type', 'notes', 'total_amount', 'cash_amount',
            'cheque_amount', 'credit_amount', 'receivable_amount', 'is_cancelled',
            'lines', 'gate_pass', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'sale_number', 'total_amount', 'cash_amount', 'cheque_amount', 'credit_amount', 'receivable_amount', 'is_cancelled', 'created_at', 'updated_at']

    def get_cheque_amount(self, obj):
        prefetched = getattr(obj, '_prefetched_objects_cache', {}).get('cheques')
        if prefetched is not None:
            amount = sum((cheque.amount for cheque in prefetched), Decimal('0.00'))
        else:
            amount = obj.cheques.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        return f'{amount.quantize(Decimal("0.01")):.2f}'

    def get_receivable_amount(self, obj):
        return f'{obj.receivable_amount.quantize(Decimal("0.01")):.2f}'

    def get_gate_pass(self, obj):
        try:
            gate_pass = obj.gate_pass
        except GatePass.DoesNotExist:
            return None
        return {
            'id': str(gate_pass.id),
            'gate_pass_number': gate_pass.gate_pass_number,
            'print_status': gate_pass.print_status,
            'issued_to_name': gate_pass.issued_to_name,
            'vehicle_number': gate_pass.vehicle_number,
            'driver_name': gate_pass.driver_name,
            'printed_at': gate_pass.printed_at,
        }


class GatePassDetailsSerializer(serializers.Serializer):
    issued_to_name = serializers.CharField(max_length=180, required=False, allow_blank=True)
    issued_to_phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    vehicle_number = serializers.CharField(max_length=80, required=False, allow_blank=True)
    driver_name = serializers.CharField(max_length=180, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class AuctionSaleCreateSerializer(serializers.Serializer):
    sale_date = serializers.DateField()
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True)
    payment_type = serializers.ChoiceField(choices=AuctionSale.PaymentType.choices)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = AuctionSaleLineWriteSerializer(many=True)
    cheque = ChequeForSaleSerializer(required=False)
    payment_breakdown = PaymentBreakdownSerializer(required=False)
    gate_pass = GatePassDetailsSerializer(required=False)

    def create(self, validated_data):
        return create_auction_sale(user=self.context['request'].user, **validated_data)

    def to_representation(self, instance):
        return AuctionSaleSerializer(instance, context=self.context).data


class AuctionSaleUpdateSerializer(serializers.Serializer):
    sale_date = serializers.DateField(required=False)
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True)
    payment_type = serializers.ChoiceField(choices=AuctionSale.PaymentType.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = AuctionSaleLineUpdateSerializer(many=True, required=False)
    payment_breakdown = PaymentBreakdownSerializer(required=False)
    cheque = ChequeForSaleSerializer(required=False)
    gate_pass = GatePassDetailsSerializer(required=False)

    def update(self, instance, validated_data):
        return update_auction_sale(user=self.context['request'].user, sale=instance, **validated_data)

    def to_representation(self, instance):
        return AuctionSaleSerializer(instance, context=self.context).data


class GatePassLineReadSerializer(serializers.ModelSerializer):
    sale_line = GatePassSaleLineReadSerializer(read_only=True)

    class Meta:
        model = GatePassLine
        fields = ['id', 'sale_line']


class GatePassSerializer(serializers.ModelSerializer):
    lines = GatePassLineReadSerializer(read_only=True, many=True)
    sale_number = serializers.CharField(source='sale.sale_number', read_only=True)

    class Meta:
        model = GatePass
        fields = [
            'id', 'gate_pass_number', 'issued_to_name', 'issued_to_phone',
            'vehicle_number', 'driver_name', 'notes', 'print_status',
            'printed_at', 'issued_at',
            'sale', 'sale_number', 'lines', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'gate_pass_number', 'print_status', 'printed_at',
            'issued_at', 'sale', 'sale_number',
            'created_at', 'updated_at',
        ]


class GatePassCreateSerializer(serializers.Serializer):
    issued_to_name = serializers.CharField(max_length=180)
    issued_to_phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    vehicle_number = serializers.CharField(max_length=80, required=False, allow_blank=True)
    driver_name = serializers.CharField(max_length=180, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    sale_line_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )

    def create(self, validated_data):
        return issue_gate_pass(user=self.context['request'].user, **validated_data)

    def to_representation(self, instance):
        return GatePassSerializer(instance, context=self.context).data


class GatePassUpdateSerializer(GatePassCreateSerializer):
    def update(self, instance, validated_data):
        return update_gate_pass(user=self.context['request'].user, gate_pass=instance, **validated_data)
