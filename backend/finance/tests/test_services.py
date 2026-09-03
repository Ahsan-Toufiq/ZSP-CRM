from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from finance.models import ChequeStatus, CustomerLedgerEntry
from finance.services import change_cheque_status, create_cheque
from operations.models import Customer


@pytest.fixture
def user(db):
    return User.objects.create_user(username='finance', password='strong-password')


@pytest.fixture
def customer(db):
    return Customer.objects.create(name='Zulfiqar Autos', phone='03000000000')


@pytest.mark.django_db
def test_cleared_cheque_posts_credit_once(user, customer):
    pending = ChequeStatus.objects.create(name='Pending')
    cleared = ChequeStatus.objects.get(name='Cleared')
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-001',
        customer=customer,
        bank_name='HBL',
        amount=Decimal('12000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate(),
        received_date=timezone.localdate(),
        status=pending,
    )

    change_cheque_status(user=user, cheque=cheque, status=cleared)

    entry = CustomerLedgerEntry.objects.get(cheque=cheque)
    assert entry.credit == Decimal('12000.00')
    assert entry.entry_type == CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT


@pytest.mark.django_db
def test_bounced_cheque_reverses_existing_settlement(user, customer):
    pending = ChequeStatus.objects.create(name='Pending')
    cleared = ChequeStatus.objects.get(name='Cleared')
    bounced = ChequeStatus.objects.get(name='Bounced')
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-002',
        customer=customer,
        bank_name='HBL',
        amount=Decimal('12000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate(),
        received_date=timezone.localdate(),
        status=pending,
    )

    change_cheque_status(user=user, cheque=cheque, status=cleared)
    change_cheque_status(user=user, cheque=cheque, status=bounced)

    entries = list(CustomerLedgerEntry.objects.filter(cheque=cheque).order_by('entry_type'))
    assert len(entries) == 2
    assert sum(entry.debit for entry in entries) == Decimal('12000.00')
    assert sum(entry.credit for entry in entries) == Decimal('12000.00')
