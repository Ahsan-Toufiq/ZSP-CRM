from decimal import Decimal

from django.db import models

from core_models import UserStampedModel
from operations.models import AuctionSale, Customer


class ChequeStatus(UserStampedModel):
    class BalanceEffect(models.TextChoices):
        NONE = 'none', 'No automatic balance effect'
        SETTLES_BALANCE = 'settles_balance', 'Settles customer balance'
        REVERSES_SETTLEMENT = 'reverses_settlement', 'Reverses previous settlement'

    name = models.CharField(max_length=80, unique=True)
    balance_effect = models.CharField(
        max_length=30,
        choices=BalanceEffect.choices,
        default=BalanceEffect.NONE,
    )
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class Cheque(UserStampedModel):
    cheque_number = models.CharField(max_length=80)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='cheques')
    name_on_cheque = models.CharField(max_length=180, blank=True)
    bank_name = models.CharField(max_length=120)
    branch_name = models.CharField(max_length=120, blank=True)
    account_title = models.CharField(max_length=180, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    cheque_date = models.DateField()
    expiry_date = models.DateField()
    received_date = models.DateField(null=True, blank=True)
    status = models.ForeignKey(ChequeStatus, on_delete=models.PROTECT, related_name='cheques')
    sale = models.ForeignKey(AuctionSale, on_delete=models.PROTECT, related_name='cheques', null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-received_date', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['cheque_number', 'bank_name'], name='unique_cheque_number_per_bank'),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='cheque_amount_positive'),
        ]
        indexes = [
            models.Index(fields=['cheque_number']),
            models.Index(fields=['cheque_date']),
            models.Index(fields=['expiry_date']),
        ]

    def __str__(self) -> str:
        return f'{self.cheque_number} - {self.customer.name}'


class ChequeStatusHistory(UserStampedModel):
    cheque = models.ForeignKey(Cheque, on_delete=models.CASCADE, related_name='status_history')
    from_status = models.ForeignKey(
        ChequeStatus,
        on_delete=models.PROTECT,
        related_name='history_from',
        null=True,
        blank=True,
    )
    to_status = models.ForeignKey(ChequeStatus, on_delete=models.PROTECT, related_name='history_to')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']


class ChequeSettlementAllocation(UserStampedModel):
    cheque = models.ForeignKey(Cheque, on_delete=models.PROTECT, related_name='settlement_allocations')
    sale = models.ForeignKey(AuctionSale, on_delete=models.PROTECT, related_name='cheque_allocations')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    is_reversed = models.BooleanField(default=False)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['sale__sale_date', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['cheque', 'sale'], name='unique_cheque_allocation_per_sale'),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='cheque_allocation_amount_positive'),
        ]
        indexes = [
            models.Index(fields=['cheque', 'is_reversed']),
            models.Index(fields=['sale', 'is_reversed']),
        ]

    def __str__(self) -> str:
        return f'{self.cheque.cheque_number} -> {self.sale.sale_number}: {self.amount}'


class CustomerLedgerEntry(UserStampedModel):
    class EntryType(models.TextChoices):
        SALE = 'sale', 'Sale'
        PAYMENT = 'payment', 'Payment'
        CHEQUE_SETTLEMENT = 'cheque_settlement', 'Cheque settlement'
        CHEQUE_REVERSAL = 'cheque_reversal', 'Cheque reversal'
        WRITE_OFF = 'write_off', 'Write-off'
        ADJUSTMENT = 'adjustment', 'Adjustment'

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='ledger_entries')
    entry_date = models.DateField()
    entry_type = models.CharField(max_length=30, choices=EntryType.choices)
    description = models.CharField(max_length=240)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    sale = models.ForeignKey(AuctionSale, on_delete=models.PROTECT, related_name='ledger_entries', null=True, blank=True)
    cheque = models.ForeignKey(Cheque, on_delete=models.PROTECT, related_name='ledger_entries', null=True, blank=True)
    payment = models.ForeignKey('CustomerPayment', on_delete=models.PROTECT, related_name='ledger_entries', null=True, blank=True)

    class Meta:
        ordering = ['entry_date', 'created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(debit__gt=0, credit=0)
                    | models.Q(credit__gt=0, debit=0)
                ),
                name='ledger_single_sided_entry',
            ),
        ]
        indexes = [
            models.Index(fields=['customer', 'entry_date']),
            models.Index(fields=['entry_type']),
        ]

    def __str__(self) -> str:
        return f'{self.customer.name} {self.entry_type} {self.entry_date}'


class CustomerPayment(UserStampedModel):
    class PaymentKind(models.TextChoices):
        CASH = 'cash', 'Cash'
        BANK_TRANSFER = 'bank_transfer', 'Bank transfer'
        CHEQUE = 'cheque', 'Cheque'
        WRITE_OFF = 'write_off', 'Write-off / balance adjustment'
        SPLIT = 'split', 'Split payment'

    payment_number = models.CharField(max_length=40, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='payments')
    payment_date = models.DateField()
    kind = models.CharField(max_length=30, choices=PaymentKind.choices)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-payment_date', '-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(total_amount__gt=0), name='customer_payment_total_positive'),
        ]
        indexes = [
            models.Index(fields=['payment_number']),
            models.Index(fields=['customer', 'payment_date']),
            models.Index(fields=['kind']),
        ]

    def __str__(self) -> str:
        return f'{self.payment_number} - {self.customer.name}'


class CustomerPaymentComponent(UserStampedModel):
    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        BANK_TRANSFER = 'bank_transfer', 'Bank transfer'
        CHEQUE = 'cheque', 'Cheque'
        WRITE_OFF = 'write_off', 'Write-off / balance adjustment'

    payment = models.ForeignKey(CustomerPayment, on_delete=models.PROTECT, related_name='components')
    method = models.CharField(max_length=30, choices=Method.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    cheque = models.OneToOneField(Cheque, on_delete=models.PROTECT, related_name='payment_component', null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['payment__payment_date', 'created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='customer_payment_component_amount_positive'),
        ]
        indexes = [
            models.Index(fields=['method']),
            models.Index(fields=['bank_name']),
        ]

    def __str__(self) -> str:
        return f'{self.payment.payment_number} / {self.method}: {self.amount}'


class CustomerPaymentAllocation(UserStampedModel):
    component = models.ForeignKey(CustomerPaymentComponent, on_delete=models.PROTECT, related_name='allocations')
    sale = models.ForeignKey(AuctionSale, on_delete=models.PROTECT, related_name='payment_allocations')
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ['sale__sale_date', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['component', 'sale'], name='unique_payment_component_allocation_per_sale'),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='payment_allocation_amount_positive'),
        ]
        indexes = [
            models.Index(fields=['component']),
            models.Index(fields=['sale']),
        ]

    def __str__(self) -> str:
        return f'{self.component.payment.payment_number} -> {self.sale.sale_number}: {self.amount}'


class Currency(UserStampedModel):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=120)
    symbol = models.CharField(max_length=12, blank=True)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['code']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.code} - {self.name}'


class CurrencyPurchase(UserStampedModel):
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='purchases')
    purchase_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    acquisition_rate = models.DecimalField(max_digits=18, decimal_places=6)
    total_cost = models.DecimalField(max_digits=18, decimal_places=2)
    source = models.CharField(max_length=160, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-purchase_date', '-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='currency_purchase_amount_positive'),
            models.CheckConstraint(condition=models.Q(acquisition_rate__gt=0), name='currency_purchase_rate_positive'),
            models.CheckConstraint(condition=models.Q(total_cost__gt=0), name='currency_purchase_total_positive'),
        ]
        indexes = [
            models.Index(fields=['currency', 'purchase_date']),
            models.Index(fields=['source']),
        ]

    def __str__(self) -> str:
        return f'{self.currency.code} {self.amount} on {self.purchase_date}'


class CurrencyOpeningBalance(UserStampedModel):
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='opening_balances')
    entry_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    acquisition_rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    total_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=160, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-entry_date', '-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='currency_opening_amount_positive'),
            models.CheckConstraint(
                condition=models.Q(acquisition_rate__isnull=True) | models.Q(acquisition_rate__gt=0),
                name='currency_opening_rate_positive_or_null',
            ),
            models.CheckConstraint(
                condition=models.Q(total_cost__isnull=True) | models.Q(total_cost__gt=0),
                name='currency_opening_total_positive_or_null',
            ),
        ]
        indexes = [models.Index(fields=['currency', 'entry_date'])]

    def __str__(self) -> str:
        return f'{self.currency.code} opening {self.amount} on {self.entry_date}'


class CurrencySpending(UserStampedModel):
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name='spending_entries')
    spending_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=4)
    purpose = models.CharField(max_length=180, blank=True)
    reference = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-spending_date', '-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='currency_spending_amount_positive'),
        ]
        indexes = [models.Index(fields=['currency', 'spending_date'])]

    def __str__(self) -> str:
        return f'{self.currency.code} spent {self.amount} on {self.spending_date}'

# Create your models here.
