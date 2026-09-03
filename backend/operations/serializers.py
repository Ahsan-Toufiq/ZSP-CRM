from django.db.models import Sum
from rest_framework import serializers

from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine
from operations.services import create_auction_sale, issue_gate_pass, update_auction_sale, update_gate_pass


class CustomerSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            'id', 'name', 'customer_type', 'phone', 'email', 'cnic_or_tax_id',
            'address', 'notes', 'is_active', 'balance', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'balance', 'created_at', 'updated_at']

    def get_balance(self, obj):
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

    class Meta:
        model = ContainerItem
        fields = [
            'id', 'container', 'container_reference', 'lot_number', 'part_name',
            'part_number', 'description', 'category', 'condition', 'quantity',
            'unit', 'reserve_price', 'status', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'container_reference', 'status', 'created_at', 'updated_at']

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

    class Meta:
        model = AuctionSaleLine
        fields = ['id', 'item', 'sold_price', 'notes']


class AuctionSaleLineWriteSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=ContainerItem.objects.all())
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class AuctionSaleLineUpdateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


class ChequeForSaleSerializer(serializers.Serializer):
    cheque_number = serializers.CharField(max_length=80)
    name_on_cheque = serializers.CharField(max_length=180)
    bank_name = serializers.CharField(max_length=120)
    branch_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    account_title = serializers.CharField(max_length=180, required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
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

    class Meta:
        model = AuctionSale
        fields = [
            'id', 'sale_number', 'sale_date', 'customer', 'customer_name',
            'payment_type', 'notes', 'total_amount', 'is_cancelled',
            'lines', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'sale_number', 'total_amount', 'is_cancelled', 'created_at', 'updated_at']


class AuctionSaleCreateSerializer(serializers.Serializer):
    sale_date = serializers.DateField()
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True)
    payment_type = serializers.ChoiceField(choices=AuctionSale.PaymentType.choices)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = AuctionSaleLineWriteSerializer(many=True)
    cheque = ChequeForSaleSerializer(required=False)

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

    class Meta:
        model = GatePass
        fields = [
            'id', 'gate_pass_number', 'issued_to_name', 'issued_to_phone',
            'vehicle_number', 'driver_name', 'notes', 'status', 'print_status',
            'printed_at', 'issued_at', 'verified_at', 'verified_by_name',
            'lines', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'gate_pass_number', 'status', 'print_status', 'printed_at',
            'issued_at', 'verified_at', 'verified_by_name', 'created_at', 'updated_at',
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
