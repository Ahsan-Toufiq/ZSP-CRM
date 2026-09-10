import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, full_tab_permissions
from catalog.models import DropdownOption
from finance.models import ChequeStatus
from operations.models import Container, ContainerItem, Customer, PartInventory


@pytest.fixture
def api_client():
    return APIClient()


def user_with_permissions(username, permissions):
    user = User.objects.create_user(username=username, password='StrongPass123!')
    normalized = {tab: AccessLevel.NONE for tab in full_tab_permissions()}
    normalized.update(permissions)
    UserProfile.objects.create(user=user, tab_permissions=normalized)
    return user


@pytest.fixture
def admin_user(db):
    return user_with_permissions('admin-test', full_tab_permissions())


@pytest.mark.django_db
def test_view_only_module_access_can_read_but_not_write(api_client):
    user = user_with_permissions('container-viewer', {'containers': AccessLevel.VIEW})
    api_client.login(username=user.username, password='StrongPass123!')

    read_response = api_client.get('/api/operations/containers/')
    write_response = api_client.post('/api/operations/containers/', {'reference': 'BLOCKED'}, format='json')

    assert read_response.status_code == 200
    assert write_response.status_code == 403


@pytest.mark.django_db
def test_full_module_access_can_write_matching_module(api_client):
    user = user_with_permissions('settings-manager', {'settings': AccessLevel.FULL})
    api_client.login(username=user.username, password='StrongPass123!')

    response = api_client.post(
        '/api/finance/cheque-statuses/',
        {'name': 'Under Review', 'balance_effect': 'none'},
        format='json',
    )

    assert response.status_code == 201


@pytest.mark.django_db
def test_disabled_module_blocks_matching_api(api_client):
    user = user_with_permissions('sales-only', {'sales': AccessLevel.FULL})
    api_client.login(username=user.username, password='StrongPass123!')

    container_response = api_client.get('/api/operations/containers/')
    sales_response = api_client.get('/api/operations/auction-sales/')

    assert container_response.status_code == 403
    assert sales_response.status_code == 200


@pytest.mark.django_db
def test_admin_can_create_user_with_tab_permissions(api_client, admin_user):
    api_client.login(username=admin_user.username, password='StrongPass123!')

    response = api_client.post(
        '/api/auth/users/',
        {
            'username': 'sales-entry',
            'first_name': 'Sales',
            'last_name': 'Operator',
            'password': 'StrongPass123!',
            'is_active': True,
            'tab_permissions': {'dashboard': 'view', 'sales': 'full'},
        },
        format='json',
    )

    assert response.status_code == 201
    user = User.objects.get(username='sales-entry')
    profile = UserProfile.objects.get(user=user)
    assert user.email == ''
    assert user.is_staff is False
    assert profile.tab_permissions['sales'] == AccessLevel.FULL
    assert profile.tab_permissions['dashboard'] == AccessLevel.VIEW
    assert profile.tab_permissions['customers'] == AccessLevel.NONE


@pytest.mark.django_db
def test_username_must_be_unique_case_insensitive(api_client, admin_user):
    User.objects.create_user(username='DuplicateName', password='StrongPass123!')
    api_client.login(username=admin_user.username, password='StrongPass123!')

    response = api_client.post(
        '/api/auth/users/',
        {
            'username': 'duplicatename',
            'first_name': 'Duplicate',
            'password': 'StrongPass123!',
            'tab_permissions': {'dashboard': 'view'},
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'username' in response.data


@pytest.mark.django_db
def test_permanent_digi7_admin_cannot_be_edited_or_deleted(api_client, admin_user):
    permanent = User.objects.create_user(username='admin', password='Admin@12345', is_active=False)
    api_client.login(username=admin_user.username, password='StrongPass123!')

    edit_response = api_client.patch(
        f'/api/auth/users/{permanent.id}/',
        {'first_name': 'Changed'},
        format='json',
    )
    delete_response = api_client.delete(f'/api/auth/users/{permanent.id}/')

    permanent.refresh_from_db()
    assert edit_response.status_code == 400
    assert delete_response.status_code == 400
    assert permanent.is_active is True
    assert permanent.is_superuser is True


@pytest.mark.django_db
def test_reset_zsp_production_data_keeps_only_handover_users_and_configuration(monkeypatch):
    dummy = User.objects.create_user(username='demo-operator', password='StrongPass123!')
    UserProfile.objects.create(user=dummy, tab_permissions=full_tab_permissions())
    customer = Customer.objects.create(name='Demo Customer', phone='+923001234567', created_by=dummy, updated_by=dummy)
    container = Container.objects.create(reference='DEMO-CNTR', created_by=dummy, updated_by=dummy)
    parent = ContainerItem.objects.create(
        container=container,
        part_name='Demo parent',
        quantity=1,
        created_by=dummy,
        updated_by=dummy,
    )
    ContainerItem.objects.create(
        container=container,
        parent_item=parent,
        part_name='Demo child',
        quantity=1,
        created_by=dummy,
        updated_by=dummy,
    )
    PartInventory.objects.create(part_name='Demo Part', quantity=3, unit='piece', created_by=dummy, updated_by=dummy)
    DropdownOption.objects.create(group=DropdownOption.Group.PART_NAME, label='Demo Part', created_by=dummy, updated_by=dummy)
    DropdownOption.objects.create(group=DropdownOption.Group.BANK, label='Demo Bank', created_by=dummy, updated_by=dummy)
    ChequeStatus.objects.create(name='Demo Status', created_by=dummy, updated_by=dummy)

    monkeypatch.setenv('RESET_ZSP_ADMIN_PASSWORD', 'AdminResetPass123!')
    monkeypatch.setenv('RESET_ZSP_CLIENT_PASSWORD', 'ClientResetPass123!')

    call_command('reset_zsp_production_data', '--confirm')

    assert set(User.objects.values_list('username', flat=True)) == {'admin', 'syed.zulfiqar'}
    admin = User.objects.get(username='admin')
    client = User.objects.get(username='syed.zulfiqar')
    assert admin.get_full_name() == 'Ahsan Toufiq'
    assert admin.is_superuser is True
    assert admin.check_password('AdminResetPass123!')
    assert client.get_full_name() == 'Syed Zulfiqar'
    assert client.is_superuser is False
    assert client.check_password('ClientResetPass123!')
    assert client.profile.tab_permissions['users'] == AccessLevel.NONE
    assert all(
        level == AccessLevel.FULL
        for tab, level in client.profile.tab_permissions.items()
        if tab != 'users'
    )
    assert Customer.objects.count() == 0
    assert Container.objects.count() == 0
    assert ContainerItem.objects.count() == 0
    assert PartInventory.objects.count() == 0
    assert DropdownOption.objects.filter(group=DropdownOption.Group.PART_NAME).count() == 0
    assert DropdownOption.objects.filter(group=DropdownOption.Group.BANK, label='Demo Bank', created_by=admin, updated_by=admin).exists()
    assert ChequeStatus.objects.filter(name='Pending', balance_effect=ChequeStatus.BalanceEffect.NONE, created_by=admin).exists()
