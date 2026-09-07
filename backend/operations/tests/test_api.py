from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import full_tab_permissions
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
