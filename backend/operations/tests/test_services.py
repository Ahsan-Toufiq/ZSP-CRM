from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalog.models import DropdownOption
from finance.models import Cheque, ChequeStatus, CustomerLedgerEntry
from finance.services import change_cheque_status
from operations.models import AuctionSale, Container, ContainerItem, GatePassLine
from operations.services import create_auction_sale, issue_gate_pass, mark_gate_pass_printed, update_auction_sale, verify_gate_pass


@pytest.fixture
def user(db):
    return User.objects.create_user(username='operator', password='strong-password')


@pytest.fixture
def customer(db):
    from operations.models import Customer

    return Customer.objects.create(name='Zulfiqar Autos', phone='+923000000000')


@pytest.fixture
def item(db):
    container = Container.objects.create(reference='CNT-001', origin_country='Japan')
    return ContainerItem.objects.create(container=container, lot_number='A-1', part_name='Headlight')


@pytest.fixture
def second_item(db):
    container = Container.objects.create(reference='CNT-002', origin_country='Japan')
    return ContainerItem.objects.create(container=container, lot_number='B-1', part_name='Bumper')


@pytest.mark.django_db
def test_credit_sale_marks_item_sold_and_posts_customer_balance(user, customer, item):
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
    )

    item.refresh_from_db()
    assert sale.total_amount == Decimal('15000.00')
    assert item.status == ContainerItem.Status.SOLD
    assert CustomerLedgerEntry.objects.get(customer=customer).debit == Decimal('15000.00')


@pytest.mark.django_db
def test_non_cash_sale_requires_customer(user, item):
    with pytest.raises(ValidationError):
        create_auction_sale(
            user=user,
            sale_date=timezone.localdate(),
            payment_type=AuctionSale.PaymentType.CREDIT,
            customer=None,
            lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
        )


@pytest.mark.django_db
def test_cash_sale_does_not_enter_customer_balance(user, item):
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CASH,
        customer=None,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
    )

    assert sale.customer is None
    assert CustomerLedgerEntry.objects.filter(sale=sale).count() == 0


@pytest.mark.django_db
def test_sold_item_cannot_be_sold_again(user, customer, item):
    create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
    )

    with pytest.raises(ValidationError):
        create_auction_sale(
            user=user,
            sale_date=timezone.localdate(),
            payment_type=AuctionSale.PaymentType.CREDIT,
            customer=customer,
            lines=[{'item': item, 'sold_price': Decimal('16000.00')}],
        )


@pytest.mark.django_db
def test_sale_can_sell_partial_container_quantity(user, customer, item):
    item.quantity = 3
    item.save(update_fields=['quantity'])

    first_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'quantity': 2, 'sold_price': Decimal('5000.00')}],
    )

    item.refresh_from_db()
    assert first_sale.total_amount == Decimal('10000.00')
    assert item.status == ContainerItem.Status.AVAILABLE

    second_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'quantity': 1, 'sold_price': Decimal('6000.00')}],
    )

    item.refresh_from_db()
    assert second_sale.total_amount == Decimal('6000.00')
    assert item.status == ContainerItem.Status.SOLD


@pytest.mark.django_db
def test_sale_auto_creates_gate_pass_and_verification_does_not_release_stock(user, customer, item):
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
    )
    sale_line = sale.lines.get()
    gate_pass = sale.gate_pass

    same_gate_pass = issue_gate_pass(
        user=user,
        sale_line_ids=[sale_line.id],
        issued_to_name='Syed Zulfiqar',
        vehicle_number='ABC-123',
    )

    item.refresh_from_db()
    assert same_gate_pass.id == gate_pass.id
    assert item.status == ContainerItem.Status.SOLD
    assert GatePassLine.objects.filter(sale_line=sale_line).count() == 1

    verify_gate_pass(user=user, gate_pass=gate_pass)
    item.refresh_from_db()
    assert item.status == ContainerItem.Status.SOLD


@pytest.mark.django_db
def test_cheque_sale_creates_cheque_and_balance_settles_only_when_cleared(user, customer, item):
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CHEQUE,
        customer=customer,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
        cheque={
            'cheque_number': 'CHQ-SALE-001',
            'name_on_cheque': 'Zulfiqar Autos',
            'bank_name': 'HBL',
            'amount': Decimal('15000.00'),
            'cheque_date': timezone.localdate(),
            'expiry_date': timezone.localdate(),
            'received_date': None,
        },
    )

    cheque = Cheque.objects.get(sale=sale)
    assert cheque.status.name == 'Pending'
    assert CustomerLedgerEntry.objects.filter(customer=customer).count() == 1
    assert CustomerLedgerEntry.objects.get(customer=customer).debit == Decimal('15000.00')

    change_cheque_status(user=user, cheque=cheque, status=ChequeStatus.objects.get(name='Cleared'))
    totals = CustomerLedgerEntry.objects.filter(customer=customer)
    assert sum(entry.debit for entry in totals) == Decimal('15000.00')
    assert sum(entry.credit for entry in totals) == Decimal('15000.00')


@pytest.mark.django_db
def test_sale_update_changes_gate_pass_lines_and_resets_print_status(user, customer, item, second_item):
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
    )
    gate_pass = sale.gate_pass
    mark_gate_pass_printed(user=user, gate_pass=gate_pass)

    update_auction_sale(
        user=user,
        sale=sale,
        customer=customer,
        lines=[
            {'id': sale.lines.get().id, 'item': item, 'quantity': 1, 'sold_price': Decimal('16000.00')},
            {'item': second_item, 'quantity': 1, 'sold_price': Decimal('12000.00')},
        ],
    )

    gate_pass.refresh_from_db()
    assert gate_pass.print_status == gate_pass.PrintStatus.NOT_PRINTED
    assert gate_pass.lines.count() == 2
    assert sale.lines.count() == 2


@pytest.mark.django_db
def test_new_item_category_persists_as_dropdown_option(user):
    from operations.serializers import ContainerItemSerializer

    container = Container.objects.create(reference='CNT-OPTION')
    serializer = ContainerItemSerializer(
        data={
            'container': str(container.id),
            'lot_number': 'OPT-1',
            'part_name': 'Custom mirror',
            'category': 'Custom Category',
            'condition': 'Refurbished',
            'quantity': 1,
            'unit': 'crate',
        },
        context={'request': type('Request', (), {'user': user})()},
    )
    assert serializer.is_valid(), serializer.errors
    serializer.save(created_by=user, updated_by=user)

    assert DropdownOption.objects.filter(group=DropdownOption.Group.ITEM_CATEGORY, label='Custom Category').exists()
    assert DropdownOption.objects.filter(group=DropdownOption.Group.ITEM_CONDITION, label='Refurbished').exists()
    assert DropdownOption.objects.filter(group=DropdownOption.Group.ITEM_UNIT, label='crate').exists()
