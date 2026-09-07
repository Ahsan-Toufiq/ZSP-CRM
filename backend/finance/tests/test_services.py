from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from finance.models import ChequeSettlementAllocation, ChequeStatus, CustomerLedgerEntry
from finance.reporting import build_credit_report
from finance.services import change_cheque_status, create_cheque
from operations.models import AuctionSale, Customer, InventoryBatch, PartInventory
from operations.services import create_auction_sale
from catalog.models import DropdownOption


@pytest.fixture
def user(db):
    return User.objects.create_user(username='finance', password='strong-password')


@pytest.fixture
def customer(db):
    return Customer.objects.create(name='Zulfiqar Autos', phone='+923000000000')


def make_batch(item):
    return InventoryBatch.objects.create(item=item, quantity=item.quantity, raw_unit_cost=Decimal('5000.00'), source_label='Test batch')


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
    first_item = PartInventory.objects.create(part_name='Gearbox', quantity=1, unit='piece')
    second_item = PartInventory.objects.create(part_name='Mirror', quantity=1, unit='piece')
    first_batch = make_batch(first_item)
    second_batch = make_batch(second_item)
    first_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': first_batch, 'sold_price': Decimal('10000.00')}],
    )
    second_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': second_batch, 'sold_price': Decimal('7000.00')}],
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
def test_overpayment_cheque_creates_customer_credit_without_crashing(user, customer):
    item = PartInventory.objects.create(part_name='Bonnet', quantity=1, unit='piece')
    batch = make_batch(item)
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('10000.00')}],
    )
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-OVERPAY-001',
        customer=customer,
        name_on_cheque='Zulfiqar Autos',
        bank_name='HBL',
        amount=Decimal('12000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate(),
        status=ChequeStatus.objects.get(name='Cleared'),
    )

    allocations = list(ChequeSettlementAllocation.objects.filter(cheque=cheque))
    entries = CustomerLedgerEntry.objects.filter(customer=customer)

    assert cheque.status.name == 'Cleared'
    assert [(allocation.sale_id, allocation.amount) for allocation in allocations] == [(sale.id, Decimal('10000.00'))]
    assert sum(entry.debit for entry in entries) - sum(entry.credit for entry in entries) == Decimal('-2000.00')


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


@pytest.mark.django_db
def test_credit_report_includes_aging_and_last_payment_date(user, customer):
    item = PartInventory.objects.create(part_name='Report alternator', quantity=2, unit='piece')
    batch = make_batch(item)
    first_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate() - timedelta(days=45),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('10000.00')}],
    )
    create_auction_sale(
        user=user,
        sale_date=timezone.localdate() - timedelta(days=95),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('7000.00')}],
    )
    cheque = create_cheque(
        user=user,
        cheque_number='CHQ-REPORT-001',
        customer=customer,
        name_on_cheque='Zulfiqar Autos',
        bank_name='HBL',
        amount=Decimal('4000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate(),
        status=ChequeStatus.objects.get(name='Cleared'),
    )

    report = build_credit_report()
    row = next(customer_row for customer_row in report.customers if customer_row['id'] == str(customer.id))

    assert row['remaining_balance'] == Decimal('13000.00')
    assert row['last_payment_date'] == timezone.localdate()
    assert row['aging']['days_31_60'] == first_sale.total_amount
    assert row['aging']['over_90'] == Decimal('3000.00')
    assert report.totals['creditor_count'] == 1
