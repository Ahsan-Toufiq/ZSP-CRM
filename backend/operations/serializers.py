from django.db.models import Sum
from rest_framework import serializers

from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine
from operations.services import (
    available_quantity_for_item,
    create_auction_sale,
    issue_gate_pass,
    sold_quantity_for_item,
    update_auction_sale,
    update_gate_pass,
)


class CustomerSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    customer_type = serializers.ChoiceField(choices=Customer.CustomerType.choices, required=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'customer_type', 'phone', 'email', 'cnic_or_tax_id',
            'address', 'notes', 'is_active', 'balance', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'balance', 'created_at', 'updated_at']

    def get_balance(self, obj):
        if hasattr(obj, 'ledger_debit') and hasattr(obj, 'ledger_credit'):
            return obj.ledger_debit - obj.ledger_credit
        totals = obj.ledger_entries.aggregate(debit=Sum('debit'), credit=Sum('credit'))
        return (totals['debit'] or 0) - (totals['credit'] or 0)

    def validate_phone(self, value):
        if not value.startswith('+') or len(value) < 8:
            raise serializers.ValidationError('Phone number must include a country code, for example +923001234567.')
        return value


class ContainerSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Container
        fields = [
            'id', 'reference', 'origin_country', 'supplier_name', 'arrival_date',
            'manifest_notes', 'status', 'item_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ContainerItemSerializer(serializers.ModelSerializer):
    container_reference = serializers.CharField(source='container.reference', read_only=True)
    sold_quantity = serializers.SerializerMethodField()
    available_quantity = serializers.SerializerMethodField()

    class Meta:
        model = ContainerItem
        fields = [
            'id', 'container', 'container_reference', 'lot_number', 'part_name',
            'part_number', 'description', 'category', 'condition', 'quantity',
            'unit', 'reserve_price', 'status', 'sold_quantity', 'available_quantity',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'container_reference', 'status', 'sold_quantity', 'available_quantity',
            'created_at', 'updated_at',
        ]

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
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CATEGORY, label=validated_data.get('category', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_CONDITION, label=validated_data.get('condition', ''), user=user)
        ensure_dropdown_option(group=DropdownOption.Group.ITEM_UNIT, label=validated_data.get('unit', ''), user=user)

    def create(self, validated_data):
        self._persist_options(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._persist_options(validated_data)
        return super().update(instance, validated_data)


class AuctionSaleLineReadSerializer(serializers.ModelSerializer):
    item = ContainerItemSerializer(read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = AuctionSaleLine
        fields = ['id', 'item', 'quantity', 'sold_price', 'line_total', 'notes']

    def get_line_total(self, obj):
        return obj.quantity * obj.sold_price


class AuctionSaleLineWriteSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=ContainerItem.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class AuctionSaleLineUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    item = serializers.PrimaryKeyRelatedField(queryset=ContainerItem.objects.all(), required=False)
    quantity = serializers.IntegerField(min_value=1)
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


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
    sale_line = AuctionSaleLineReadSerializer(read_only=True)

    class Meta:
        model = GatePassLine
        fields = ['id', 'sale_line']


class GatePassSerializer(serializers.ModelSerializer):
    lines = GatePassLineReadSerializer(read_only=True, many=True)
    verified_by_name = serializers.CharField(source='verified_by.get_full_name', read_only=True)
    sale_number = serializers.CharField(source='sale.sale_number', read_only=True)

    class Meta:
        model = GatePass
        fields = [
            'id', 'gate_pass_number', 'issued_to_name', 'issued_to_phone',
            'vehicle_number', 'driver_name', 'notes', 'status', 'print_status',
            'printed_at', 'issued_at', 'verified_at', 'verified_by_name',
            'sale', 'sale_number', 'lines', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'gate_pass_number', 'status', 'print_status', 'printed_at',
            'issued_at', 'verified_at', 'verified_by_name', 'sale', 'sale_number',
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
