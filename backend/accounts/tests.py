import pytest
from django.contrib.auth.models import Group, User
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import Roles


@pytest.fixture
def api_client():
    return APIClient()


def user_with_role(username, role):
    group = Group.objects.create(name=role)
    user = User.objects.create_user(username=username, password='StrongPass123!')
    user.groups.add(group)
    return user


@pytest.fixture
def admin_user(db):
    return user_with_role('admin-test', Roles.ADMIN)


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


@pytest.mark.django_db
def test_admin_can_create_user_with_limited_tab_access(api_client, admin_user):
    api_client.login(username=admin_user.username, password='StrongPass123!')

    response = api_client.post(
        '/api/auth/users/',
        {
            'username': 'sales-only',
            'first_name': 'Sales',
            'last_name': 'Operator',
            'email': 'sales-only@example.com',
            'password': 'StrongPass123!',
            'is_active': True,
            'is_staff': False,
            'roles': [Roles.OPERATIONS],
            'access_tabs': ['sales'],
        },
        format='json',
    )

    assert response.status_code == 201
    user = User.objects.get(username='sales-only')
    assert list(user.groups.values_list('name', flat=True)) == [Roles.OPERATIONS]
    assert UserProfile.objects.get(user=user).allowed_tabs == ['sales']


@pytest.mark.django_db
def test_disabled_tab_blocks_matching_api_even_when_role_allows_it(api_client):
    user = user_with_role('containers-blocked', Roles.OPERATIONS)
    UserProfile.objects.create(user=user, allowed_tabs=['sales'])
    api_client.login(username=user.username, password='StrongPass123!')

    container_response = api_client.get('/api/operations/containers/')
    sales_response = api_client.get('/api/operations/auction-sales/')

    assert container_response.status_code == 403
    assert sales_response.status_code == 200
