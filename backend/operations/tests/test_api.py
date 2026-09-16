from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import full_tab_permissions
from finance.models import CustomerLedgerEntry
from operations.models import AuctionSale, Container, ContainerItem, Customer, InventoryBatch, PartInventory
from operations.services import create_auction_sale


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(username='api-admin', password='StrongPass123!')
    UserProfile.objects.create(user=user, tab_permissions=full_tab_permissions())
    return user


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.login(username=admin_user.username, password='StrongPass123!')
    return client


@pytest.mark.django_db
def test_customer_without_transactions_can_be_deleted(api_client):
    customer = Customer.objects.create(name='Delete Me', phone='+923001231231')

    response = api_client.delete(f'/api/operations/customers/{customer.id}/')

    assert response.status_code == 204
    assert not Customer.objects.filter(id=customer.id).exists()


@pytest.mark.django_db
def test_customer_type_defaults_when_omitted(api_client):
    response = api_client.post(
        '/api/operations/customers/',
        {'name': 'Default Type Customer', 'phone': '+923001231233'},
        format='json',
    )

    assert response.status_code == 201
    assert response.data['customer_type'] == Customer.CustomerType.INDIVIDUAL


@pytest.mark.django_db
def test_customer_opening_balance_creates_receivable_ledger_entry(api_client):
    response = api_client.post(
        '/api/operations/customers/',
        {
            'name': 'Opening Balance Customer',
            'phone': '+923001231234',
            'opening_balance': '25000.00',
            'opening_balance_direction': 'receivable',
        },
        format='json',
    )

    assert response.status_code == 201
    customer = Customer.objects.get(id=response.data['id'])
    entry = CustomerLedgerEntry.objects.get(customer=customer)
    assert entry.entry_type == CustomerLedgerEntry.EntryType.ADJUSTMENT
    assert entry.description == 'Opening balance'
    assert entry.debit == Decimal('25000.00')
    assert entry.credit == Decimal('0.00')


@pytest.mark.django_db
def test_customer_opening_balance_can_record_customer_credit(api_client):
    response = api_client.post(
        '/api/operations/customers/',
        {
            'name': 'Advance Customer',
            'phone': '+923001231235',
            'opening_balance': '5000.00',
            'opening_balance_direction': 'credit',
        },
        format='json',
    )

    assert response.status_code == 201
    entry = CustomerLedgerEntry.objects.get(customer_id=response.data['id'])
    assert entry.debit == Decimal('0.00')
    assert entry.credit == Decimal('5000.00')


@pytest.mark.django_db
def test_customer_without_opening_balance_has_no_ledger_entry(api_client):
    response = api_client.post(
        '/api/operations/customers/',
        {'name': 'No Opening Balance', 'phone': '+923001231236'},
        format='json',
    )

    assert response.status_code == 201
    assert CustomerLedgerEntry.objects.filter(customer_id=response.data['id']).count() == 0


@pytest.mark.django_db
def test_customer_opening_balance_can_be_edited(api_client):
    response = api_client.post(
        '/api/operations/customers/',
        {
            'name': 'Editable Opening Balance',
            'phone': '+923001231237',
            'opening_balance': '25000.00',
            'opening_balance_direction': 'receivable',
        },
        format='json',
    )
    assert response.status_code == 201

    update = api_client.patch(
        f"/api/operations/customers/{response.data['id']}/",
        {
            'opening_balance': '8000.00',
            'opening_balance_direction': 'credit',
        },
        format='json',
    )

    assert update.status_code == 200
    entry = CustomerLedgerEntry.objects.get(customer_id=response.data['id'])
    assert entry.debit == Decimal('0.00')
    assert entry.credit == Decimal('8000.00')
    assert update.data['opening_balance'] == '8000.00'
    assert update.data['opening_balance_direction'] == 'credit'


@pytest.mark.django_db
def test_customer_opening_balance_can_be_removed(api_client):
    response = api_client.post(
        '/api/operations/customers/',
        {
            'name': 'Removable Opening Balance',
            'phone': '+923001231238',
            'opening_balance': '12000.00',
        },
        format='json',
    )

    update = api_client.patch(
        f"/api/operations/customers/{response.data['id']}/",
        {'opening_balance': '0.00'},
        format='json',
    )

    assert update.status_code == 200
    assert CustomerLedgerEntry.objects.filter(customer_id=response.data['id']).count() == 0


@pytest.mark.django_db
def test_customer_with_transactions_cannot_be_deleted(api_client, admin_user):
    customer = Customer.objects.create(name='Keep Me', phone='+923001231232')
    item = PartInventory.objects.create(part_name='Door', quantity=1, unit='piece')
    batch = InventoryBatch.objects.create(item=item, quantity=1, raw_unit_cost=Decimal('5000.00'), source_label='Test batch')
    create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('15000.00')}],
    )

    response = api_client.delete(f'/api/operations/customers/{customer.id}/')

    assert response.status_code == 409
    assert response.data['blocking_records']['auction_sales'] == 1
    assert Customer.objects.filter(id=customer.id).exists()


@pytest.mark.django_db
def test_empty_container_can_be_deleted(api_client):
    container = Container.objects.create(reference='DELETE-EMPTY')

    response = api_client.delete(f'/api/operations/containers/{container.id}/')

    assert response.status_code == 204
    assert not Container.objects.filter(id=container.id).exists()


@pytest.mark.django_db
def test_container_with_inventory_returns_conflict_on_delete(api_client):
    container = Container.objects.create(reference='KEEP-WITH-STOCK')
    ContainerItem.objects.create(
        container=container,
        part_name='Mirror',
        category='Body',
        quantity=1,
        unit='piece',
        raw_unit_cost=Decimal('2000.00'),
    )

    response = api_client.delete(f'/api/operations/containers/{container.id}/')

    assert response.status_code == 409
    assert response.data['protected_records'] == 1
    assert Container.objects.filter(id=container.id).exists()


@pytest.mark.django_db
def test_subpart_split_over_available_quantity_returns_validation_error(api_client):
    container = Container.objects.create(reference='CNT-API-SUB', status=Container.Status.READY_FOR_AUCTION)
    parent_part = PartInventory.objects.create(
        part_name='Damaged lamp',
        part_number='D-LAMP',
        category='Lights',
        quantity=1,
        unit='piece',
    )
    parent = ContainerItem.objects.create(
        container=container,
        part_name='Damaged lamp',
        part_number='D-LAMP',
        category='Lights',
        quantity=1,
        unit='piece',
        raw_unit_cost=Decimal('5000.00'),
        net_unit_cost=Decimal('5000.00'),
    )
    InventoryBatch.objects.create(
        item=parent_part,
        container=container,
        container_item=parent,
        quantity=1,
        raw_unit_cost=parent.raw_unit_cost,
        net_unit_cost=parent.net_unit_cost,
    )

    response = api_client.post(
        f'/api/operations/items/{parent.id}/subparts/',
        {
            'split_quantity': 2,
            'subparts': [
                {
                    'part_name': 'Lamp clip',
                    'part_number': 'CLIP',
                    'category': 'Lights',
                    'quantity': 1,
                    'unit': 'piece',
                    'raw_unit_cost': '100.00',
                },
            ],
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'split_quantity' in response.data
    parent.refresh_from_db()
    assert parent.quantity == 1


@pytest.mark.django_db
def test_inventory_report_spreadsheet_excludes_zero_available_batches(api_client, admin_user):
    container = Container.objects.create(reference='REPORT-CNT', created_by=admin_user, updated_by=admin_user)
    item = PartInventory.objects.create(part_name='Report light', category='Lights', quantity=2, unit='piece')
    available_batch = InventoryBatch.objects.create(
        item=item,
        container=container,
        quantity=2,
        raw_unit_cost=Decimal('1000.00'),
        net_unit_cost=Decimal('1200.00'),
    )
    create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CASH,
        lines=[{'inventory_batch': available_batch, 'quantity': 1, 'sold_price': Decimal('1500.00')}],
    )
    sold_out_item = PartInventory.objects.create(part_name='Sold out report part', quantity=1, unit='piece')
    sold_out_batch = InventoryBatch.objects.create(
        item=sold_out_item,
        container=container,
        quantity=1,
        raw_unit_cost=Decimal('100.00'),
        net_unit_cost=Decimal('100.00'),
    )
    create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CASH,
        lines=[{'inventory_batch': sold_out_batch, 'quantity': 1, 'sold_price': Decimal('150.00')}],
    )

    response = api_client.get(f'/api/operations/inventory-report/?export=csv&container={container.id}')

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Report light' in body
    assert 'Sold out report part' not in body
    assert 'Available quantity' in body


@pytest.mark.django_db
def test_sale_invoice_pdf_endpoint_returns_pdf(api_client, admin_user):
    customer = Customer.objects.create(name='Invoice Customer', phone='+923009999991')
    item = PartInventory.objects.create(part_name='Invoice bumper', quantity=1, unit='piece')
    batch = InventoryBatch.objects.create(item=item, quantity=1, raw_unit_cost=Decimal('5000.00'), net_unit_cost=Decimal('6000.00'))
    sale = create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('9500.00')}],
    )

    response = api_client.get(f'/api/operations/auction-sales/{sale.id}/invoice/')

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF')


@pytest.mark.django_db
def test_sales_analytics_returns_daily_monthly_yearly_totals(api_client, admin_user):
    item = PartInventory.objects.create(part_name='Analytics mirror', quantity=2, unit='piece')
    batch = InventoryBatch.objects.create(item=item, quantity=2, raw_unit_cost=Decimal('1000.00'), net_unit_cost=Decimal('1200.00'))
    create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CASH,
        lines=[{'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('2500.00')}],
    )

    response = api_client.get('/api/operations/auction-sales/analytics/')

    assert response.status_code == 200
    assert response.data['totals']['sale_count'] >= 1
    assert response.data['daily']
    assert response.data['monthly']
    assert response.data['yearly']
    assert response.data['selected']
    assert response.data['date_bounds']['oldest_sale_date']
    assert response.data['date_bounds']['latest_sale_date']


@pytest.mark.django_db
def test_sales_analytics_supports_bounded_date_range_and_granularity(api_client, admin_user):
    item = PartInventory.objects.create(part_name='Range analytics part', quantity=2, unit='piece')
    first_batch = InventoryBatch.objects.create(item=item, quantity=1, raw_unit_cost=Decimal('100.00'), net_unit_cost=Decimal('120.00'))
    second_batch = InventoryBatch.objects.create(item=item, quantity=1, raw_unit_cost=Decimal('100.00'), net_unit_cost=Decimal('120.00'))
    first_date = timezone.localdate() - timedelta(days=60)
    second_date = timezone.localdate()
    create_auction_sale(
        user=admin_user,
        sale_date=first_date,
        payment_type=AuctionSale.PaymentType.CASH,
        lines=[{'inventory_batch': first_batch, 'quantity': 1, 'sold_price': Decimal('500.00')}],
    )
    create_auction_sale(
        user=admin_user,
        sale_date=second_date,
        payment_type=AuctionSale.PaymentType.CASH,
        lines=[{'inventory_batch': second_batch, 'quantity': 1, 'sold_price': Decimal('700.00')}],
    )

    response = api_client.get(f'/api/operations/auction-sales/analytics/?start={first_date}&end={second_date}&granularity=year')

    assert response.status_code == 200
    assert response.data['date_bounds']['start'] == first_date
    assert response.data['date_bounds']['end'] == second_date
    assert response.data['date_bounds']['granularity'] == 'year'
    assert len(response.data['selected']) >= 1
