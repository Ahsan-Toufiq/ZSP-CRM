from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from accounts.models import UserProfile
from catalog.models import DropdownOption
from finance.models import ChequeStatus, Currency
from operations.models import Container, ContainerItem, Customer, PartInventory


@pytest.mark.django_db
def test_purge_command_dry_run_changes_nothing():
    user = User.objects.create_user(username='preserved', password='StrongPass123!')
    UserProfile.objects.create(user=user, tab_permissions={'dashboard': 'view'})
    Customer.objects.create(name='Demo customer', phone='+923001111111')

    output = StringIO()
    call_command('purge_business_data', stdout=output)

    assert User.objects.filter(pk=user.pk).exists()
    assert Customer.objects.filter(name='Demo customer').exists()
    assert 'Dry run only' in output.getvalue()


@pytest.mark.django_db
def test_purge_command_removes_business_data_and_preserves_users_and_system_config():
    user = User.objects.create_user(
        username='preserved', password='StrongPass123!', first_name='Permanent', is_active=True,
    )
    profile = UserProfile.objects.create(user=user, tab_permissions={'dashboard': 'view', 'containers': 'full'})
    before_password = user.password
    before_permissions = profile.tab_permissions.copy()
    system_currency = Currency.objects.get(code='USD')
    system_status = ChequeStatus.objects.get(name='Pending')
    system_option = DropdownOption.objects.filter(is_system=True).first()
    custom_currency = Currency.objects.create(code='ZZZ', name='Test currency')
    custom_option = DropdownOption.objects.create(group=DropdownOption.Group.PART_NAME, label='Test part', value='test-part')
    Customer.objects.create(name='Demo customer', phone='+923001111111')
    container = Container.objects.create(reference='DEMO-CONTAINER')
    parent = ContainerItem.objects.create(container=container, part_name='Parent part', quantity=1)
    ContainerItem.objects.create(
        container=container,
        parent_item=parent,
        part_name='Child part',
        quantity=1,
    )
    PartInventory.objects.create(part_name='Demo part', quantity=0)

    call_command(
        'purge_business_data',
        execute=True,
        confirm='PURGE-NON-USER-BUSINESS-DATA',
        expected_user_count=1,
        stdout=StringIO(),
    )

    user.refresh_from_db()
    profile.refresh_from_db()
    assert user.password == before_password
    assert user.first_name == 'Permanent'
    assert profile.tab_permissions == before_permissions
    assert Customer.objects.count() == 0
    assert Container.objects.count() == 0
    assert ContainerItem.objects.count() == 0
    assert PartInventory.objects.count() == 0
    assert Currency.objects.filter(pk=system_currency.pk).exists()
    assert ChequeStatus.objects.filter(pk=system_status.pk).exists()
    assert system_option is None or DropdownOption.objects.filter(pk=system_option.pk).exists()
    assert not Currency.objects.filter(pk=custom_currency.pk).exists()
    assert not DropdownOption.objects.filter(pk=custom_option.pk).exists()
