from django.core.exceptions import ValidationError
from django.db import transaction

from audit.models import AuditLog
from finance.models import Cheque, ChequeStatus, ChequeStatusHistory, CustomerLedgerEntry


@transaction.atomic
def create_cheque(*, user, **data) -> Cheque:
    cheque = Cheque.objects.create(created_by=user, updated_by=user, **data)
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
    return cheque


@transaction.atomic
def change_cheque_status(*, user, cheque: Cheque, status: ChequeStatus, notes='') -> Cheque:
    cheque = Cheque.objects.select_for_update().select_related('status', 'customer').get(id=cheque.id)
    previous_status = cheque.status
    if previous_status_id := getattr(previous_status, 'id', None):
        if previous_status_id == status.id:
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
        if cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists():
            raise ValidationError({'status': 'This cheque has already posted a settlement entry.'})
        CustomerLedgerEntry.objects.create(
            customer=cheque.customer,
            entry_date=cheque.received_date,
            entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT,
            description=f'Cheque settlement {cheque.cheque_number}',
            credit=cheque.amount,
            cheque=cheque,
            created_by=user,
            updated_by=user,
        )
    elif status.balance_effect == ChequeStatus.BalanceEffect.REVERSES_SETTLEMENT:
        settled = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists()
        reversed_once = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_REVERSAL).exists()
        if settled and not reversed_once:
            CustomerLedgerEntry.objects.create(
                customer=cheque.customer,
                entry_date=cheque.received_date,
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
