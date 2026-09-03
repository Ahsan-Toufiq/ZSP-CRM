import pytest
from django.contrib.auth.models import Group, User
from rest_framework.test import APIClient

from accounts.permissions import Roles


@pytest.fixture
def api_client():
    return APIClient()


def user_with_role(username, role):
    group = Group.objects.create(name=role)
    user = User.objects.create_user(username=username, password='StrongPass123!')
    user.groups.add(group)
    return user


@pytest.mark.django_db
def test_gatekeeper_can_read_gate_passes_but_cannot_manage_customers(api_client):
    gatekeeper = user_with_role('gatekeeper-test', Roles.GATEKEEPER)
    api_client.login(username=gatekeeper.username, password='StrongPass123!')

    gate_pass_response = api_client.get('/api/operations/gate-passes/')
    customer_response = api_client.post('/api/operations/customers/', {'name': 'Blocked customer'})

    assert gate_pass_response.status_code == 200
    assert customer_response.status_code == 403


@pytest.mark.django_db
def test_finance_can_manage_cheque_statuses_but_cannot_create_inventory(api_client):
    finance = user_with_role('finance-test', Roles.FINANCE)
    api_client.login(username=finance.username, password='StrongPass123!')

    cheque_status_response = api_client.post(
        '/api/finance/cheque-statuses/',
        {'name': 'Under Review', 'balance_effect': 'none'},
        format='json',
    )
    inventory_response = api_client.post('/api/operations/items/', {'lot_number': 'LOT-X'})

    assert cheque_status_response.status_code == 201
    assert inventory_response.status_code == 403
