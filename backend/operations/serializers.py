from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine, InventoryBatch, PartInventory
from operations.services import (
    apply_container_inventory_delta,
    available_quantity_for_batch,
    available_quantity_for_item,
    create_auction_sale,
    issue_gate_pass,
    net_unit_cost_for_batch,
    sold_quantity_for_item,
    sold_quantity_for_batch,
    sync_manual_inventory_batch_delta,
    update_auction_sale,
    update_gate_pass,
)


class CustomerSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    customer_type = serializers.ChoiceField(choices=Customer.CustomerType.choices, required=False, default=Customer.CustomerType.INDIVIDUAL)

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'customer_type', 'phone', 'email', 'cnic_or_tax_id',
            'address', 'notes', 'is_active', 'balance', 'can_delete', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'balance', 'can_delete', 'created_at', 'updated_at']

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


class ContainerItemSerializer(serializers.ModelSerializer):
    container_reference = serializers.CharField(source='container.reference', read_only=True)
    raw_total_cost = serializers.SerializerMethodField()
    added_cost_share = serializers.SerializerMethodField()
    net_unit_cost = serializers.SerializerMethodField()
    net_total_cost = serializers.SerializerMethodField()

    class Meta:
        model = ContainerItem
        fields = [
            'id', 'container', 'container_reference', 'lot_number', 'part_name',
            'part_number', 'description', 'category', 'condition', 'quantity',
            'unit', 'reserve_price', 'raw_unit_cost', 'raw_total_cost',
            'added_cost_share', 'net_unit_cost', 'net_total_cost', 'status',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'container_reference', 'status',
            'created_at', 'updated_at',
        ]

    def get_raw_total_cost(self, obj):
        return obj.raw_unit_cost * obj.quantity

    def get_added_cost_share(self, obj):
        raw_total = self.get_raw_total_cost(obj)
        container_raw_cost = getattr(obj, 'container_raw_parts_cost_total', None)
        if container_raw_cost is None:
            container_raw_cost = getattr(obj.container, 'raw_parts_cost_total', None)
        if container_raw_cost is None:
            container_raw_cost = sum((item.raw_unit_cost * item.quantity for item in obj.container.items.all()), Decimal('0.00'))
        if not container_raw_cost:
            return Decimal('0.00')
        return (obj.container.added_cost or Decimal('0.00')) * (raw_total / container_raw_cost)

    def get_net_total_cost(self, obj):
        return self.get_raw_total_cost(obj) + self.get_added_cost_share(obj)

    def get_net_unit_cost(self, obj):
        if not obj.quantity:
            return Decimal('0.00')
        return self.get_net_total_cost(obj) / obj.quantity

    def _persist_options(self, validated_data):
        user = self.context['request'].user
        ensure_dropdown_option(group=DropdownOption.Group.PART_NAME, label=validated_data.get('part_name', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CATEGORY, label=validated_data.get('category', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CONDITION, label=validated_data.get('condition', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_UNIT, label=validated_data.get('unit', ''), user=user)

    def _snapshot(self, instance):
        return {
            'container_item_id': instance.id,
            'part_name': instance.part_name,
            'part_number': instance.part_number or '',
            'category': instance.category or '',
            'condition': instance.condition or '',
            'unit': instance.unit or 'piece',
            'quantity': instance.quantity,
            'reserve_price': instance.reserve_price,
            'raw_unit_cost': instance.raw_unit_cost,
            'description': instance.description or '',
        }

    def create(self, validated_data):
        self._persist_options(validated_data)
        with transaction.atomic():
            instance = super().create(validated_data)
            apply_container_inventory_delta(user=self.context['request'].user, after=instance)
            return instance

    def update(self, instance, validated_data):
        self._persist_options(validated_data)
        with transaction.atomic():
            before = self._snapshot(instance)
            instance = super().update(instance, validated_data)
            apply_container_inventory_delta(user=self.context['request'].user, before=before, after=instance)
            return instance


class InventoryBatchSerializer(serializers.ModelSerializer):
    container_reference = serializers.CharField(source='container.reference', read_only=True)
    part_name = serializers.CharField(source='item.part_name', read_only=True)
    part_number = serializers.CharField(source='item.part_number', read_only=True)
    category = serializers.CharField(source='item.category', read_only=True)
    condition = serializers.CharField(source='item.condition', read_only=True)
    unit = serializers.CharField(source='item.unit', read_only=True)
    sold_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()
    net_unit_cost = serializers.SerializerMethodField()

    class Meta:
        model = InventoryBatch
        fields = [
            'id', 'item', 'part_name', 'part_number', 'category', 'condition',
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


class PartInventorySerializer(serializers.ModelSerializer):
    sold_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()
    batches = InventoryBatchSerializer(read_only=True, many=True)

    class Meta:
        model = PartInventory
        fields = [
            'id', 'part_name', 'part_number', 'description', 'category',
            'condition', 'quantity', 'unit', 'reserve_price', 'sold_quantity',
            'available_quantity', 'batches', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'sold_quantity', 'available_quantity', 'batches', 'created_at', 'updated_at']

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
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CONDITION, label=validated_data.get('condition', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_UNIT, label=validated_data.get('unit', ''), user=user)

    def validate(self, attrs):
        quantity = attrs.get('quantity', getattr(self.instance, 'quantity', 0))
        if self.instance is not None and quantity < sold_quantity_for_item(self.instance):
            raise serializers.ValidationError({'quantity': 'Quantity cannot be lower than the quantity already sold.'})
        return attrs

    def create(self, validated_data):
        self._persist_options(validated_data)
        with transaction.atomic():
            instance = super().create(validated_data)
            sync_manual_inventory_batch_delta(user=self.context['request'].user, item=instance, before_quantity=0)
            return instance

    def update(self, instance, validated_data):
        self._persist_options(validated_data)
        before_quantity = instance.quantity
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            sync_manual_inventory_batch_delta(
                user=self.context['request'].user,
                item=instance,
                before_quantity=before_quantity,
            )
            return instance


class AuctionSaleLineReadSerializer(serializers.ModelSerializer):
    item = serializers.SerializerMethodField()
    inventory_batch_label = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = AuctionSaleLine
        fields = [
            'id', 'item', 'inventory_batch', 'inventory_batch_label',
            'quantity', 'sold_price', 'raw_unit_cost_snapshot',
            'net_unit_cost_snapshot', 'line_total', 'notes',
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
            'condition': item.condition,
            'quantity': item.quantity,
            'unit': item.unit,
            'reserve_price': item.reserve_price,
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
            'condition': item.condition,
            'quantity': item.quantity,
            'unit': item.unit,
            'reserve_price': item.reserve_price,
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


class AuctionSaleSerializer(serializers.ModelSerializer):
    lines = AuctionSaleLineReadSerializer(read_only=True, many=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    gate_pass = serializers.SerializerMethodField()

    class Meta:
        model = AuctionSale
        fields = [
            'id', 'sale_number', 'sale_date', 'customer', 'customer_name',
            'payment_type', 'notes', 'total_amount', 'is_cancelled',
            'lines', 'gate_pass', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'sale_number', 'total_amount', 'is_cancelled', 'created_at', 'updated_at']

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
