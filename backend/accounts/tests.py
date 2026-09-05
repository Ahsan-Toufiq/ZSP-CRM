import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, full_tab_permissions


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
