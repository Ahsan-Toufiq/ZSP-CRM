from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from finance.models import ChequeSettlementAllocation, ChequeStatus, CustomerLedgerEntry
from finance.services import change_cheque_status, create_cheque
from operations.models import AuctionSale, Container, ContainerItem, Customer
from operations.services import create_auction_sale
from catalog.models import DropdownOption


@pytest.fixture
def user(db):
    return User.objects.create_user(username='finance', password='strong-password')


@pytest.fixture
def customer(db):
    return Customer.objects.create(name='Zulfiqar Autos', phone='+923000000000')


@pytest.mark.django_db
def test_cleared_cheque_posts_credit_once(user, customer):
    pending = ChequeStatus.objects.get(name='Pending')
    cleared = ChequeStatus.objects.get(name='Cleared')
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-001',
        customer=customer,
        name_on_cheque='Zulfiqar Autos',
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
    pending = ChequeStatus.objects.get(name='Pending')
    cleared = ChequeStatus.objects.get(name='Cleared')
    bounced = ChequeStatus.objects.get(name='Bounced')
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-002',
        customer=customer,
        name_on_cheque='Zulfiqar Autos',
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


@pytest.mark.django_db
def test_individual_cleared_cheque_allocates_to_oldest_sales_first(user, customer):
    container = Container.objects.create(reference='CNT-FIN-001')
    first_item = ContainerItem.objects.create(container=container, lot_number='F-1', part_name='Gearbox')
    second_item = ContainerItem.objects.create(container=container, lot_number='F-2', part_name='Mirror')
    first_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': first_item, 'sold_price': Decimal('10000.00')}],
    )
    second_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': second_item, 'sold_price': Decimal('7000.00')}],
    )
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-SPLIT-001',
        customer=customer,
        name_on_cheque='Ahsan Toufiq',
        bank_name='HBL',
        amount=Decimal('12000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate(),
        status=ChequeStatus.objects.get(name='Pending'),
    )

    change_cheque_status(user=user, cheque=cheque, status=ChequeStatus.objects.get(name='Cleared'))

    allocations = list(ChequeSettlementAllocation.objects.filter(cheque=cheque).order_by('sale__sale_date', 'created_at'))
    assert [(allocation.sale_id, allocation.amount) for allocation in allocations] == [
        (first_sale.id, Decimal('10000.00')),
        (second_sale.id, Decimal('2000.00')),
    ]


@pytest.mark.django_db
def test_new_cheque_bank_persists_as_dropdown_option(user, customer):
    pending = ChequeStatus.objects.get(name='Pending')
    create_cheque(
        user=user,
        cheque_number='CHQ-NEW-BANK',
        customer=customer,
        name_on_cheque='Zulfiqar Autos',
        bank_name='Custom Test Bank',
        amount=Decimal('12000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate(),
        status=pending,
    )

    assert DropdownOption.objects.filter(group=DropdownOption.Group.BANK, label='Custom Test Bank').exists()
