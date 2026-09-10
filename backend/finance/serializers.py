from django.db.models import Sum
from rest_framework import serializers

from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from finance.models import Cheque, ChequeSettlementAllocation, ChequeStatus, ChequeStatusHistory, CustomerLedgerEntry
from finance.services import change_cheque_status, create_cheque
from operations.models import AuctionSale, Customer


class ChequeStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChequeStatus
        fields = ['id', 'name', 'balance_effect', 'is_system', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_system', 'created_at', 'updated_at']


class ChequeSettlementAllocationSerializer(serializers.ModelSerializer):
    sale_number = serializers.CharField(source='sale.sale_number', read_only=True)
    sale_date = serializers.DateField(source='sale.sale_date', read_only=True)

    class Meta:
        model = ChequeSettlementAllocation
        fields = ['id', 'cheque', 'sale', 'sale_number', 'sale_date', 'amount', 'is_reversed', 'created_at']
        read_only_fields = fields


class ChequeSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    status_name = serializers.CharField(source='status.name', read_only=True)
    name_on_cheque = serializers.CharField(max_length=180)
    settlement_allocations = ChequeSettlementAllocationSerializer(read_only=True, many=True)

    class Meta:
        model = Cheque
        fields = [
            'id', 'cheque_number', 'customer', 'customer_name', 'name_on_cheque',
            'bank_name', 'branch_name', 'account_title', 'amount', 'cheque_date',
            'expiry_date', 'received_date', 'status', 'status_name', 'sale',
            'settlement_allocations', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'customer_name', 'status_name', 'settlement_allocations', 'created_at', 'updated_at']

    def validate(self, attrs):
        cheque_date = attrs.get('cheque_date', getattr(self.instance, 'cheque_date', None))
        expiry_date = attrs.get('expiry_date', getattr(self.instance, 'expiry_date', None))
        if cheque_date and expiry_date and expiry_date < cheque_date:
            raise serializers.ValidationError({'expiry_date': 'Expiry date cannot be before cheque date.'})
        return attrs

    def create(self, validated_data):
        return create_cheque(user=self.context['request'].user, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('status', None)
        bank_name = validated_data.get('bank_name')
        if bank_name:
            ensure_dropdown_option(group=DropdownOption.Group.BANK, label=bank_name, user=self.context['request'].user)
        return super().update(instance, validated_data)


class ChequeStatusChangeSerializer(serializers.Serializer):
    status = serializers.PrimaryKeyRelatedField(queryset=ChequeStatus.objects.filter(is_active=True))
    notes = serializers.CharField(required=False, allow_blank=True)

    def save(self, **kwargs):
        return change_cheque_status(
            user=self.context['request'].user,
            cheque=self.context['cheque'],
            status=self.validated_data['status'],
            notes=self.validated_data.get('notes', ''),
        )


class ChequeStatusHistorySerializer(serializers.ModelSerializer):
    from_status_name = serializers.CharField(source='from_status.name', read_only=True)
    to_status_name = serializers.CharField(source='to_status.name', read_only=True)

    class Meta:
        model = ChequeStatusHistory
        fields = ['id', 'cheque', 'from_status_name', 'to_status_name', 'notes', 'created_at']
        read_only_fields = fields


class CustomerLedgerEntrySerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    sale_number = serializers.CharField(source='sale.sale_number', read_only=True)
    cheque_number = serializers.CharField(source='cheque.cheque_number', read_only=True)

    class Meta:
        model = CustomerLedgerEntry
        fields = [
            'id', 'customer', 'customer_name', 'entry_date', 'entry_type',
            'description', 'debit', 'credit', 'sale', 'sale_number', 'cheque',
            'cheque_number', 'created_at',
        ]
        read_only_fields = ['id', 'customer_name', 'created_at']


class CustomerBalanceSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    total_debit = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()
    sale_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'balance', 'total_debit', 'total_credit', 'sale_breakdown']

    def _totals(self, obj):
        if hasattr(obj, 'ledger_debit') and hasattr(obj, 'ledger_credit'):
            return {'debit': obj.ledger_debit, 'credit': obj.ledger_credit}
        if not hasattr(obj, '_ledger_totals'):
            obj._ledger_totals = obj.ledger_entries.aggregate(debit=Sum('debit'), credit=Sum('credit'))
        return obj._ledger_totals

    def get_total_debit(self, obj):
        return self._totals(obj)['debit'] or 0

    def get_total_credit(self, obj):
        return self._totals(obj)['credit'] or 0

    def get_balance(self, obj):
        return self.get_total_debit(obj) - self.get_total_credit(obj)

    def get_sale_breakdown(self, obj):
        sales = obj.auction_sales.all()
        breakdown = []
        for sale in sales:
            allocations = [
                {
                    'id': str(allocation.id),
                    'cheque': str(allocation.cheque_id),
                    'cheque_number': allocation.cheque.cheque_number,
                    'amount': allocation.amount,
                    'is_reversed': allocation.is_reversed,
                    'created_at': allocation.created_at,
                }
                for allocation in sale.cheque_allocations.all()
            ]
            active_allocated = sum((allocation['amount'] for allocation in allocations if not allocation['is_reversed']), 0)
            receivable_amount = sale.receivable_amount
            breakdown.append({
                'id': str(sale.id),
                'sale_number': sale.sale_number,
                'sale_date': sale.sale_date,
                'total_amount': sale.total_amount,
                'settled_amount': active_allocated,
                'outstanding_amount': receivable_amount - active_allocated,
                'items': [
                    {
                        'part_name': line.item.part_name,
                        'quantity': line.quantity,
                        'unit_price': line.sold_price,
                        'line_total': line.quantity * line.sold_price,
                    }
                    for line in sale.lines.all()
                ],
                'settlements': allocations,
            })
        return breakdown
