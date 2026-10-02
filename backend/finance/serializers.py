from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from finance.models import (
    Cheque,
    ChequeSettlementAllocation,
    ChequeStatus,
    ChequeStatusHistory,
    Currency,
    CurrencyCreditor,
    CurrencyCreditorRepayment,
    CurrencyOpeningBalance,
    CurrencyPurchase,
    CurrencySpending,
    Expense,
    CustomerLedgerEntry,
    CustomerPayment,
    CustomerPaymentAllocation,
    CustomerPaymentComponent,
    CustomerPaymentTarget,
)
from finance.services import (
    change_cheque_status,
    create_cheque,
    create_currency_opening_balance,
    create_currency_creditor_repayment,
    create_currency_spending,
    resolve_currency_creditor,
    update_currency_creditor_repayment,
    update_currency_purchase,
    update_currency_opening_balance,
    record_customer_payment,
    resolve_currency,
    update_currency_spending,
)
from operations.models import AuctionSale, Customer


class ChequeStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChequeStatus
        fields = ['id', 'name', 'balance_effect', 'is_system', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_system', 'created_at', 'updated_at']


class ChequeSettlementAllocationSerializer(serializers.ModelSerializer):
    sale_number = serializers.SerializerMethodField()
    sale_date = serializers.SerializerMethodField()
    target_type = serializers.SerializerMethodField()
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = ChequeSettlementAllocation
        fields = ['id', 'cheque', 'sale', 'opening_balance', 'sale_number', 'sale_date', 'target_type', 'target_label', 'amount', 'is_reversed', 'created_at']
        read_only_fields = fields

    def get_sale_number(self, obj):
        return obj.sale.sale_number if obj.sale_id else None

    def get_sale_date(self, obj):
        return obj.sale.sale_date if obj.sale_id else obj.opening_balance.entry_date

    def get_target_type(self, obj):
        return 'sale' if obj.sale_id else 'opening_balance'

    def get_target_label(self, obj):
        return obj.sale.sale_number if obj.sale_id else 'Opening balance'


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
    payment_number = serializers.CharField(source='payment.payment_number', read_only=True)

    class Meta:
        model = CustomerLedgerEntry
        fields = [
            'id', 'customer', 'customer_name', 'entry_date', 'entry_type',
            'description', 'debit', 'credit', 'sale', 'sale_number', 'cheque',
            'cheque_number', 'payment', 'payment_number', 'created_at',
        ]
        read_only_fields = ['id', 'customer_name', 'created_at']


class CustomerPaymentAllocationSerializer(serializers.ModelSerializer):
    sale_number = serializers.SerializerMethodField()
    sale_date = serializers.SerializerMethodField()
    target_type = serializers.SerializerMethodField()
    target_label = serializers.SerializerMethodField()

    class Meta:
        model = CustomerPaymentAllocation
        fields = ['id', 'component', 'sale', 'opening_balance', 'sale_number', 'sale_date', 'target_type', 'target_label', 'amount', 'created_at']
        read_only_fields = fields

    def get_sale_number(self, obj):
        return obj.sale.sale_number if obj.sale_id else None

    def get_sale_date(self, obj):
        return obj.sale.sale_date if obj.sale_id else obj.opening_balance.entry_date

    def get_target_type(self, obj):
        return 'sale' if obj.sale_id else 'opening_balance'

    def get_target_label(self, obj):
        return obj.sale.sale_number if obj.sale_id else 'Opening balance'


class CustomerPaymentTargetSerializer(serializers.ModelSerializer):
    target_type = serializers.SerializerMethodField()
    target_label = serializers.SerializerMethodField()
    target_date = serializers.SerializerMethodField()

    class Meta:
        model = CustomerPaymentTarget
        fields = ['id', 'sale', 'opening_balance', 'target_type', 'target_label', 'target_date', 'amount']
        read_only_fields = fields

    def get_target_type(self, obj):
        return 'sale' if obj.sale_id else 'opening_balance'

    def get_target_label(self, obj):
        return obj.sale.sale_number if obj.sale_id else 'Opening balance'

    def get_target_date(self, obj):
        return obj.sale.sale_date if obj.sale_id else obj.opening_balance.entry_date


class CustomerPaymentComponentSerializer(serializers.ModelSerializer):
    cheque_number = serializers.CharField(source='cheque.cheque_number', read_only=True)
    cheque_status = serializers.CharField(source='cheque.status.name', read_only=True)
    allocations = CustomerPaymentAllocationSerializer(read_only=True, many=True)

    class Meta:
        model = CustomerPaymentComponent
        fields = [
            'id', 'method', 'amount', 'reference', 'bank_name', 'cheque',
            'cheque_number', 'cheque_status', 'notes', 'allocations',
        ]
        read_only_fields = fields


class CustomerPaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    components = CustomerPaymentComponentSerializer(read_only=True, many=True)
    targets = CustomerPaymentTargetSerializer(read_only=True, many=True)

    class Meta:
        model = CustomerPayment
        fields = [
            'id', 'payment_number', 'customer', 'customer_name', 'payment_date',
            'kind', 'allocation_mode', 'total_amount', 'reference', 'notes', 'components', 'targets',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class CustomerPaymentChequeSerializer(serializers.Serializer):
    cheque_number = serializers.CharField(max_length=80)
    name_on_cheque = serializers.CharField(max_length=180, required=False, allow_blank=True)
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


class CustomerPaymentComponentWriteSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=CustomerPaymentComponent.Method.choices)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    bank_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    cheque = CustomerPaymentChequeSerializer(required=False)

    def validate(self, attrs):
        method = attrs['method']
        if method == CustomerPaymentComponent.Method.BANK_TRANSFER and not attrs.get('bank_name'):
            raise serializers.ValidationError({'bank_name': 'Bank name is required for bank transfers.'})
        if method == CustomerPaymentComponent.Method.CHEQUE and not attrs.get('cheque'):
            raise serializers.ValidationError({'cheque': 'Cheque details are required for cheque payments.'})
        if method == CustomerPaymentComponent.Method.WRITE_OFF and not attrs.get('notes', '').strip():
            raise serializers.ValidationError({'notes': 'An adjustment reason is required for write-offs.'})
        return attrs


class CustomerPaymentCreateSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_active=True))
    payment_date = serializers.DateField()
    allocation_mode = serializers.ChoiceField(choices=CustomerPayment.AllocationMode.choices, default=CustomerPayment.AllocationMode.OVERALL)
    notes = serializers.CharField(required=False, allow_blank=True)
    components = CustomerPaymentComponentWriteSerializer(many=True)
    targets = serializers.ListField(child=serializers.DictField(), required=False, default=list)

    def validate_components(self, value):
        if not value:
            raise serializers.ValidationError('At least one payment component is required.')
        return value

    def create(self, validated_data):
        try:
            return record_customer_payment(user=self.context['request'].user, **validated_data)
        except ValueError as exc:
            raise serializers.ValidationError({'detail': str(exc)}) from exc

    def to_representation(self, instance):
        return CustomerPaymentSerializer(instance, context=self.context).data


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
            cheque_allocations = [
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
            payment_allocations = [
                {
                    'id': str(allocation.id),
                    'payment_number': allocation.component.payment.payment_number,
                    'method': allocation.component.method,
                    'amount': allocation.amount,
                    'created_at': allocation.created_at,
                }
                for allocation in sale.payment_allocations.all()
            ]
            active_allocated = (
                sum((allocation['amount'] for allocation in cheque_allocations if not allocation['is_reversed']), 0)
                + sum((allocation['amount'] for allocation in payment_allocations), 0)
            )
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
                'settlements': [*cheque_allocations, *payment_allocations],
            })
        return breakdown


class CurrencySerializer(serializers.ModelSerializer):
    current_amount = serializers.SerializerMethodField()
    total_purchased = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    average_acquisition_rate = serializers.SerializerMethodField()
    purchase_count = serializers.SerializerMethodField()
    opening_balance_count = serializers.SerializerMethodField()
    spending_count = serializers.SerializerMethodField()
    total_opening = serializers.SerializerMethodField()
    total_currency_spent = serializers.SerializerMethodField()
    total_acquisition_cost = serializers.SerializerMethodField()
    has_activity = serializers.SerializerMethodField()

    class Meta:
        model = Currency
        fields = [
            'id', 'code', 'name', 'symbol', 'is_system', 'is_active',
            'current_amount', 'total_purchased', 'total_spent',
            'total_opening', 'total_currency_spent', 'total_acquisition_cost',
            'average_acquisition_rate', 'purchase_count', 'opening_balance_count',
            'spending_count', 'has_activity', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'is_system', 'created_at', 'updated_at']

    def _summary(self, obj):
        if not hasattr(obj, '_currency_summary'):
            purchases = list(obj.purchases.all())
            openings = list(obj.opening_balances.all())
            spending_entries = list(obj.spending_entries.all())
            purchased = sum((purchase.amount for purchase in purchases), Decimal('0.0000'))
            opening = sum((entry.amount for entry in openings), Decimal('0.0000'))
            currency_spent = sum((entry.amount for entry in spending_entries), Decimal('0.0000'))
            paid_purchases = [purchase for purchase in purchases if purchase.total_cost is not None]
            repayments = [repayment for purchase in purchases for repayment in purchase.repayments.all()]
            acquisition_cost = sum((purchase.total_cost for purchase in paid_purchases), Decimal('0.00'))
            acquisition_cost += sum((repayment.total_cost for repayment in repayments), Decimal('0.00'))
            known_openings = [entry for entry in openings if entry.total_cost is not None]
            acquisition_cost += sum((entry.total_cost for entry in known_openings), Decimal('0.00'))
            known_amount = sum((purchase.amount for purchase in paid_purchases), Decimal('0.0000'))
            known_amount += sum((repayment.amount for repayment in repayments), Decimal('0.0000'))
            known_amount += sum((entry.amount for entry in known_openings), Decimal('0.0000'))
            obj._currency_summary = {
                'current': purchased + opening - currency_spent,
                'purchased': purchased,
                'opening': opening,
                'currency_spent': currency_spent,
                'acquisition_cost': acquisition_cost,
                'known_amount': known_amount,
                'purchase_count': len(purchases),
                'opening_count': len(openings),
                'spending_count': len(spending_entries),
            }
        return obj._currency_summary

    def get_current_amount(self, obj):
        return self._summary(obj)['current']

    def get_total_purchased(self, obj):
        return self._summary(obj)['purchased']

    def get_total_spent(self, obj):
        return self._summary(obj)['acquisition_cost']

    def get_total_opening(self, obj):
        return self._summary(obj)['opening']

    def get_total_currency_spent(self, obj):
        return self._summary(obj)['currency_spent']

    def get_total_acquisition_cost(self, obj):
        return self._summary(obj)['acquisition_cost']

    def get_average_acquisition_rate(self, obj):
        summary = self._summary(obj)
        if summary['known_amount'] <= 0:
            return Decimal('0.000000')
        return (summary['acquisition_cost'] / summary['known_amount']).quantize(Decimal('0.000001'))

    def get_purchase_count(self, obj):
        return self._summary(obj)['purchase_count']

    def get_opening_balance_count(self, obj):
        return self._summary(obj)['opening_count']

    def get_spending_count(self, obj):
        return self._summary(obj)['spending_count']

    def get_has_activity(self, obj):
        summary = self._summary(obj)
        return bool(summary['purchase_count'] or summary['opening_count'] or summary['spending_count'])

    def validate_code(self, value):
        return value.upper()


class CurrencyReferenceSerializerMixin:
    def validate(self, attrs):
        if not attrs.get('currency') and not attrs.get('currency_input') and self.instance is None:
            raise serializers.ValidationError({'currency_input': 'Select a currency or enter a new one.'})
        return super().validate(attrs)

    def _resolve_currency(self, validated_data):
        selected = validated_data.pop('currency', None)
        currency_input = validated_data.pop('currency_input', '')
        if selected is None and not currency_input and self.instance is not None:
            return self.instance.currency
        try:
            return resolve_currency(
                currency=selected,
                currency_input=currency_input,
                user=self.context['request'].user,
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class CurrencyPurchaseSerializer(CurrencyReferenceSerializerMixin, serializers.ModelSerializer):
    currency = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all(), required=False)
    currency_input = serializers.CharField(write_only=True, required=False, allow_blank=False)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)
    currency_symbol = serializers.CharField(source='currency.symbol', read_only=True)
    creditor = serializers.PrimaryKeyRelatedField(queryset=CurrencyCreditor.objects.all(), required=False, allow_null=True)
    creditor_input = serializers.CharField(write_only=True, required=False, allow_blank=True)
    creditor_name = serializers.CharField(source='creditor.name', read_only=True, allow_null=True)
    repaid_amount = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    outstanding_amount = serializers.DecimalField(max_digits=18, decimal_places=4, read_only=True)
    repayment_count = serializers.SerializerMethodField()

    class Meta:
        model = CurrencyPurchase
        fields = [
            'id', 'currency', 'currency_input', 'currency_code', 'currency_name', 'currency_symbol',
            'purchase_type', 'creditor', 'creditor_input', 'creditor_name', 'purchase_date', 'due_date',
            'amount', 'acquisition_rate', 'total_cost', 'repaid_amount', 'outstanding_amount', 'repayment_count',
            'source', 'reference', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'currency_code', 'currency_name', 'currency_symbol', 'created_at', 'updated_at']
        extra_kwargs = {
            'acquisition_rate': {'required': False, 'allow_null': True},
            'total_cost': {'required': False, 'allow_null': True},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        amount = attrs.get('amount', getattr(self.instance, 'amount', None))
        purchase_type = attrs.get('purchase_type', getattr(self.instance, 'purchase_type', CurrencyPurchase.PurchaseType.CASH))
        rate = attrs.get('acquisition_rate', getattr(self.instance, 'acquisition_rate', None))
        total = attrs.get('total_cost', getattr(self.instance, 'total_cost', None))
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be greater than zero.'})
        if purchase_type == CurrencyPurchase.PurchaseType.CREDIT:
            creditor = attrs.get('creditor', getattr(self.instance, 'creditor', None))
            creditor_input = str(attrs.get('creditor_input', '')).strip()
            if creditor is None and not creditor_input:
                raise serializers.ValidationError({'creditor_input': 'Select a creditor or enter a new creditor name.'})
            attrs['acquisition_rate'] = None
            attrs['total_cost'] = None
            return attrs
        attrs['creditor'] = None
        attrs['due_date'] = None
        if not rate and not total:
            raise serializers.ValidationError({'acquisition_rate': 'Enter either acquisition rate or total purchase cost.'})
        if rate is not None and rate <= 0:
            raise serializers.ValidationError({'acquisition_rate': 'Acquisition rate must be greater than zero.'})
        if total is not None and total <= 0:
            raise serializers.ValidationError({'total_cost': 'Total purchase cost must be greater than zero.'})
        if rate and not total:
            attrs['total_cost'] = (amount * rate).quantize(Decimal('0.01'))
        elif total and not rate:
            attrs['acquisition_rate'] = (total / amount).quantize(Decimal('0.000001'))
        return attrs

    def create(self, validated_data):
        validated_data['currency'] = self._resolve_currency(validated_data)
        creditor_input = validated_data.pop('creditor_input', '')
        if validated_data.get('purchase_type') == CurrencyPurchase.PurchaseType.CREDIT:
            validated_data['creditor'] = resolve_currency_creditor(
                creditor=validated_data.get('creditor'),
                creditor_input=creditor_input,
                user=self.context['request'].user,
            )
        return super().create(validated_data)

    def update(self, instance, validated_data):
        currency = self._resolve_currency(validated_data)
        creditor_input = validated_data.pop('creditor_input', '')
        if validated_data.get('purchase_type', instance.purchase_type) == CurrencyPurchase.PurchaseType.CREDIT:
            validated_data['creditor'] = resolve_currency_creditor(
                creditor=validated_data.get('creditor', instance.creditor),
                creditor_input=creditor_input,
                user=self.context['request'].user,
            )
        user = validated_data.pop('updated_by')
        try:
            return update_currency_purchase(instance=instance, user=user, currency=currency, **validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def get_repayment_count(self, obj):
        return obj.repayments.count()


class CurrencyCreditorSerializer(serializers.ModelSerializer):
    outstanding_by_currency = serializers.SerializerMethodField()
    purchase_count = serializers.SerializerMethodField()
    repayment_count = serializers.SerializerMethodField()
    overdue_count = serializers.SerializerMethodField()
    total_pkr_repaid = serializers.SerializerMethodField()

    class Meta:
        model = CurrencyCreditor
        fields = [
            'id', 'name', 'phone', 'address', 'notes', 'is_active',
            'outstanding_by_currency', 'purchase_count', 'repayment_count',
            'overdue_count', 'total_pkr_repaid', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'outstanding_by_currency', 'purchase_count', 'repayment_count',
            'overdue_count', 'total_pkr_repaid', 'created_at', 'updated_at',
        ]

    def _summary(self, obj):
        if not hasattr(obj, '_creditor_summary'):
            today = timezone.localdate()
            balances = {}
            repayment_count = 0
            total_pkr_repaid = Decimal('0.00')
            overdue_count = 0
            for purchase in obj.credit_purchases.all():
                repayments = list(purchase.repayments.all())
                repaid = sum((entry.amount for entry in repayments), Decimal('0.0000'))
                outstanding = max(Decimal(purchase.amount) - repaid, Decimal('0.0000'))
                code = purchase.currency.code
                balances[code] = balances.get(code, Decimal('0.0000')) + outstanding
                repayment_count += len(repayments)
                total_pkr_repaid += sum((entry.total_cost for entry in repayments), Decimal('0.00'))
                if purchase.due_date and purchase.due_date < today and outstanding > 0:
                    overdue_count += 1
            obj._creditor_summary = {
                'balances': [
                    {'currency_code': code, 'amount': amount}
                    for code, amount in sorted(balances.items()) if amount > 0
                ],
                'purchase_count': len(obj.credit_purchases.all()),
                'repayment_count': repayment_count,
                'overdue_count': overdue_count,
                'total_pkr_repaid': total_pkr_repaid,
            }
        return obj._creditor_summary

    def get_outstanding_by_currency(self, obj):
        return self._summary(obj)['balances']

    def get_purchase_count(self, obj):
        return self._summary(obj)['purchase_count']

    def get_repayment_count(self, obj):
        return self._summary(obj)['repayment_count']

    def get_overdue_count(self, obj):
        return self._summary(obj)['overdue_count']

    def get_total_pkr_repaid(self, obj):
        return self._summary(obj)['total_pkr_repaid']


class CurrencyCreditorRepaymentSerializer(serializers.ModelSerializer):
    purchase = serializers.PrimaryKeyRelatedField(queryset=CurrencyPurchase.objects.filter(purchase_type=CurrencyPurchase.PurchaseType.CREDIT))
    creditor_id = serializers.UUIDField(source='purchase.creditor_id', read_only=True)
    creditor_name = serializers.CharField(source='purchase.creditor.name', read_only=True)
    currency_code = serializers.CharField(source='purchase.currency.code', read_only=True)
    purchase_reference = serializers.CharField(source='purchase.reference', read_only=True)

    class Meta:
        model = CurrencyCreditorRepayment
        fields = [
            'id', 'purchase', 'purchase_reference', 'creditor_id', 'creditor_name',
            'currency_code', 'repayment_date', 'amount', 'exchange_rate', 'total_cost',
            'reference', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'purchase_reference', 'creditor_id', 'creditor_name', 'currency_code',
            'created_at', 'updated_at',
        ]
        extra_kwargs = {
            'exchange_rate': {'required': False, 'allow_null': True},
            'total_cost': {'required': False, 'allow_null': True},
        }

    def validate(self, attrs):
        amount = attrs.get('amount', getattr(self.instance, 'amount', None))
        rate = attrs.get('exchange_rate', getattr(self.instance, 'exchange_rate', None))
        total = attrs.get('total_cost', getattr(self.instance, 'total_cost', None))
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Repayment amount must be greater than zero.'})
        if not rate and not total:
            raise serializers.ValidationError({'exchange_rate': 'Enter either the exchange rate or total PKR paid.'})
        if rate is not None and rate <= 0:
            raise serializers.ValidationError({'exchange_rate': 'Exchange rate must be greater than zero.'})
        if total is not None and total <= 0:
            raise serializers.ValidationError({'total_cost': 'Total PKR paid must be greater than zero.'})
        if rate and not total:
            attrs['total_cost'] = (amount * rate).quantize(Decimal('0.01'))
        elif total and not rate:
            attrs['exchange_rate'] = (total / amount).quantize(Decimal('0.000001'))
        if self.instance and 'purchase' in attrs and attrs['purchase'].id != self.instance.purchase_id:
            raise serializers.ValidationError({'purchase': 'The liability cannot change after a repayment is recorded.'})
        return attrs

    def create(self, validated_data):
        user = validated_data.pop('created_by')
        validated_data.pop('updated_by', None)
        try:
            return create_currency_creditor_repayment(user=user, **validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def update(self, instance, validated_data):
        validated_data.pop('purchase', None)
        user = validated_data.pop('updated_by')
        try:
            return update_currency_creditor_repayment(instance=instance, user=user, **validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class CurrencyOpeningBalanceSerializer(CurrencyReferenceSerializerMixin, serializers.ModelSerializer):
    currency = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all(), required=False)
    currency_input = serializers.CharField(write_only=True, required=False, allow_blank=False)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)

    class Meta:
        model = CurrencyOpeningBalance
        fields = [
            'id', 'currency', 'currency_input', 'currency_code', 'currency_name',
            'entry_date', 'amount', 'acquisition_rate', 'total_cost',
            'source', 'reference', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'currency_code', 'currency_name', 'created_at', 'updated_at']
        extra_kwargs = {
            'acquisition_rate': {'required': False, 'allow_null': True},
            'total_cost': {'required': False, 'allow_null': True},
        }

    def validate(self, attrs):
        attrs = super().validate(attrs)
        amount = attrs.get('amount', getattr(self.instance, 'amount', None))
        rate = attrs.get('acquisition_rate', getattr(self.instance, 'acquisition_rate', None))
        total = attrs.get('total_cost', getattr(self.instance, 'total_cost', None))
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be greater than zero.'})
        if rate is not None and rate <= 0:
            raise serializers.ValidationError({'acquisition_rate': 'Acquisition rate must be greater than zero.'})
        if total is not None and total <= 0:
            raise serializers.ValidationError({'total_cost': 'Total cost must be greater than zero.'})
        if rate and not total:
            attrs['total_cost'] = (amount * rate).quantize(Decimal('0.01'))
        elif total and not rate:
            attrs['acquisition_rate'] = (total / amount).quantize(Decimal('0.000001'))
        return attrs

    def create(self, validated_data):
        currency = validated_data.pop('currency', None)
        currency_input = validated_data.pop('currency_input', '')
        user = validated_data.pop('created_by')
        validated_data.pop('updated_by', None)
        try:
            return create_currency_opening_balance(
                user=user,
                currency=currency,
                currency_input=currency_input,
                **validated_data,
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def update(self, instance, validated_data):
        currency = self._resolve_currency(validated_data)
        user = validated_data.pop('updated_by')
        try:
            return update_currency_opening_balance(instance=instance, user=user, currency=currency, **validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class CurrencySpendingSerializer(CurrencyReferenceSerializerMixin, serializers.ModelSerializer):
    currency = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all(), required=False)
    currency_input = serializers.CharField(write_only=True, required=False, allow_blank=False)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)

    class Meta:
        model = CurrencySpending
        fields = [
            'id', 'currency', 'currency_input', 'currency_code', 'currency_name',
            'spending_date', 'amount', 'purpose', 'reference', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'currency_code', 'currency_name', 'created_at', 'updated_at']

    def validate(self, attrs):
        attrs = super().validate(attrs)
        amount = attrs.get('amount', getattr(self.instance, 'amount', None))
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be greater than zero.'})
        return attrs

    def create(self, validated_data):
        currency = validated_data.pop('currency', None)
        currency_input = validated_data.pop('currency_input', '')
        user = validated_data.pop('created_by')
        validated_data.pop('updated_by', None)
        try:
            return create_currency_spending(
                user=user,
                currency=currency,
                currency_input=currency_input,
                **validated_data,
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def update(self, instance, validated_data):
        currency = validated_data.pop('currency', None)
        currency_input = validated_data.pop('currency_input', '')
        user = validated_data.pop('updated_by')
        try:
            return update_currency_spending(
                instance=instance,
                user=user,
                currency=currency if currency is not None or currency_input else instance.currency,
                currency_input=currency_input,
                **validated_data,
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = [
            'id', 'expense_date', 'title', 'category', 'amount', 'payee',
            'payment_method', 'reference', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value

    def _persist_options(self, validated_data):
        user = self.context['request'].user
        groups = {
            'title': DropdownOption.Group.EXPENSE_TITLE,
            'category': DropdownOption.Group.EXPENSE_CATEGORY,
            'payee': DropdownOption.Group.EXPENSE_PAYEE,
            'payment_method': DropdownOption.Group.EXPENSE_PAYMENT_METHOD,
        }
        for field, group in groups.items():
            ensure_dropdown_option(group=group, label=validated_data.get(field, ''), user=user)

    def create(self, validated_data):
        self._persist_options(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._persist_options(validated_data)
        return super().update(instance, validated_data)
