from django.db.models import Sum
from rest_framework import serializers

from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine
from operations.services import create_auction_sale, issue_gate_pass


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


class AuctionSaleLineReadSerializer(serializers.ModelSerializer):
    item = ContainerItemSerializer(read_only=True)

    class Meta:
        model = AuctionSaleLine
        fields = ['id', 'item', 'sold_price', 'notes']


class AuctionSaleLineWriteSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=ContainerItem.objects.all())
    sold_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    notes = serializers.CharField(required=False, allow_blank=True)


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

    def create(self, validated_data):
        return create_auction_sale(user=self.context['request'].user, **validated_data)

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
            'vehicle_number', 'driver_name', 'notes', 'status', 'issued_at',
            'verified_at', 'verified_by_name', 'lines', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'gate_pass_number', 'status', 'issued_at', 'verified_at',
            'verified_by_name', 'created_at', 'updated_at',
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
