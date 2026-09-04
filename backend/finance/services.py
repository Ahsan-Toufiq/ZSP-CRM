from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from finance.models import Cheque, ChequeSettlementAllocation, ChequeStatus, ChequeStatusHistory, CustomerLedgerEntry
from operations.models import AuctionSale


@transaction.atomic
def create_cheque(*, user, **data) -> Cheque:
    ensure_dropdown_option(group=DropdownOption.Group.BANK, label=data.get('bank_name', ''), user=user)
    requested_status = data.pop('status')
    initial_status = requested_status
    if requested_status.balance_effect != ChequeStatus.BalanceEffect.NONE:
        initial_status = (
            ChequeStatus.objects
            .filter(name='Pending', balance_effect=ChequeStatus.BalanceEffect.NONE, is_active=True)
            .first()
            or requested_status
        )
    cheque = Cheque.objects.create(created_by=user, updated_by=user, status=initial_status, **data)
    ChequeStatusHistory.objects.create(
        cheque=cheque,
        from_status=None,
        to_status=cheque.status,
        notes='Cheque created',
        created_by=user,
        updated_by=user,
    )
    AuditLog.objects.create(
        actor=user,
        action='cheque.created',
        entity_type='Cheque',
        entity_id=str(cheque.id),
        message=f'Created cheque {cheque.cheque_number}',
        metadata={'amount': str(cheque.amount), 'status': cheque.status.name},
    )
    if requested_status.id != initial_status.id:
        cheque = change_cheque_status(user=user, cheque=cheque, status=requested_status, notes='Initial cheque status')
    return cheque


def _active_allocated_amount(sale: AuctionSale) -> Decimal:
    return sale.cheque_allocations.filter(is_reversed=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def _allocate_cheque_to_oldest_sales(*, user, cheque: Cheque) -> None:
    remaining = Decimal(cheque.amount)
    sales = (
        AuctionSale.objects
        .select_for_update()
        .filter(
            customer=cheque.customer,
            payment_type__in=[
                AuctionSale.PaymentType.CREDIT,
                AuctionSale.PaymentType.CHEQUE,
                AuctionSale.PaymentType.MIXED,
            ],
            is_cancelled=False,
        )
        .order_by('sale_date', 'created_at')
    )

    for sale in sales:
        if remaining <= 0:
            break
        outstanding = Decimal(sale.total_amount) - _active_allocated_amount(sale)
        if outstanding <= 0:
            continue
        amount = min(remaining, outstanding)
        ChequeSettlementAllocation.objects.create(
            cheque=cheque,
            sale=sale,
            amount=amount,
            created_by=user,
            updated_by=user,
        )
        remaining -= amount


def _post_cheque_settlement(*, user, cheque: Cheque) -> None:
    existing_settlement = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists()
    active_allocations = cheque.settlement_allocations.filter(is_reversed=False).exists()
    if existing_settlement:
        if active_allocations:
            return
        allocated_once = cheque.settlement_allocations.exists()
        if allocated_once:
            return
    CustomerLedgerEntry.objects.create(
        customer=cheque.customer,
        entry_date=cheque.received_date or timezone.localdate(),
        entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT,
        description=f'Cheque settlement {cheque.cheque_number}',
        credit=cheque.amount,
        cheque=cheque,
        created_by=user,
        updated_by=user,
    )
    _allocate_cheque_to_oldest_sales(user=user, cheque=cheque)


@transaction.atomic
def change_cheque_status(*, user, cheque: Cheque, status: ChequeStatus, notes='') -> Cheque:
    cheque = Cheque.objects.select_for_update().select_related('status', 'customer').get(id=cheque.id)
    previous_status = cheque.status
    if previous_status_id := getattr(previous_status, 'id', None):
        if previous_status_id == status.id:
            if status.balance_effect == ChequeStatus.BalanceEffect.SETTLES_BALANCE:
                _post_cheque_settlement(user=user, cheque=cheque)
            return cheque

    cheque.status = status
    cheque.updated_by = user
    cheque.save(update_fields=['status', 'updated_by', 'updated_at'])

    ChequeStatusHistory.objects.create(
        cheque=cheque,
        from_status=previous_status,
        to_status=status,
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    if status.balance_effect == ChequeStatus.BalanceEffect.SETTLES_BALANCE:
        _post_cheque_settlement(user=user, cheque=cheque)
    elif status.balance_effect == ChequeStatus.BalanceEffect.REVERSES_SETTLEMENT:
        settled = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists()
        reversed_once = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_REVERSAL).exists()
        if settled and not reversed_once:
            cheque.settlement_allocations.filter(is_reversed=False).update(
                is_reversed=True,
                reversed_at=timezone.now(),
                updated_by=user,
            )
            CustomerLedgerEntry.objects.create(
                customer=cheque.customer,
                entry_date=cheque.received_date or timezone.localdate(),
                entry_type=CustomerLedgerEntry.EntryType.CHEQUE_REVERSAL,
                description=f'Cheque reversal {cheque.cheque_number}',
                debit=cheque.amount,
                cheque=cheque,
                created_by=user,
                updated_by=user,
            )

    AuditLog.objects.create(
        actor=user,
        action='cheque.status_changed',
        entity_type='Cheque',
        entity_id=str(cheque.id),
        message=f'Changed cheque {cheque.cheque_number} status to {status.name}',
        metadata={'from': previous_status.name, 'to': status.name},
    )
    return cheque
