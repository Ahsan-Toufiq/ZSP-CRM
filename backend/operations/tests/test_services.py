from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from finance.models import CustomerLedgerEntry
from operations.models import AuctionSale, Container, ContainerItem, GatePassLine
from operations.services import create_auction_sale, issue_gate_pass, verify_gate_pass


@pytest.fixture
def user(db):
    return User.objects.create_user(username='operator', password='strong-password')


@pytest.fixture
def customer(db):
    from operations.models import Customer

    return Customer.objects.create(name='Zulfiqar Autos', phone='03000000000')


@pytest.fixture
def item(db):
    container = Container.objects.create(reference='CNT-001', origin_country='Japan')
    return ContainerItem.objects.create(container=container, lot_number='A-1', part_name='Headlight')


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
def test_gate_pass_can_be_issued_once_and_then_verified(user, customer, item):
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'item': item, 'sold_price': Decimal('15000.00')}],
    )
    sale_line = sale.lines.get()

    gate_pass = issue_gate_pass(
        user=user,
        sale_line_ids=[sale_line.id],
        issued_to_name='Syed Zulfiqar',
        vehicle_number='ABC-123',
    )

    item.refresh_from_db()
    assert item.status == ContainerItem.Status.GATE_PASS_ISSUED
    assert GatePassLine.objects.filter(sale_line=sale_line).count() == 1

    with pytest.raises(ValidationError):
        issue_gate_pass(
            user=user,
            sale_line_ids=[sale_line.id],
            issued_to_name='Syed Zulfiqar',
        )

    verify_gate_pass(user=user, gate_pass=gate_pass)
    item.refresh_from_db()
    assert item.status == ContainerItem.Status.RELEASED
