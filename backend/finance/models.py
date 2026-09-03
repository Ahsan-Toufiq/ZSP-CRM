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


class CustomerLedgerEntry(UserStampedModel):
    class EntryType(models.TextChoices):
        SALE = 'sale', 'Sale'
        PAYMENT = 'payment', 'Payment'
        CHEQUE_SETTLEMENT = 'cheque_settlement', 'Cheque settlement'
        CHEQUE_REVERSAL = 'cheque_reversal', 'Cheque reversal'
        ADJUSTMENT = 'adjustment', 'Adjustment'

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='ledger_entries')
    entry_date = models.DateField()
    entry_type = models.CharField(max_length=30, choices=EntryType.choices)
    description = models.CharField(max_length=240)
    debit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    sale = models.ForeignKey(AuctionSale, on_delete=models.PROTECT, related_name='ledger_entries', null=True, blank=True)
    cheque = models.ForeignKey(Cheque, on_delete=models.PROTECT, related_name='ledger_entries', null=True, blank=True)
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

# Create your models here.
