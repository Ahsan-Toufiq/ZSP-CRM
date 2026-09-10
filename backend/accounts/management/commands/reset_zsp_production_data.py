import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, ALL_TABS, PERMANENT_ADMIN_USERNAME, full_tab_permissions
from accounts.serializers import enforce_permanent_admin
from audit.models import AuditLog
from catalog.models import DropdownOption
from finance.models import Cheque, ChequeSettlementAllocation, ChequeStatus, ChequeStatusHistory, CustomerLedgerEntry
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine, InventoryBatch, PartInventory


PAKISTAN_BANKS = [
    'Al Baraka Bank (Pakistan) Limited',
    'Allied Bank Limited',
    'Askari Bank Limited',
    'Bank AL Habib Limited',
    'Bank Alfalah Limited',
    'BankIslami Pakistan Limited',
    'Bank Makramah Limited',
    'Citibank N.A.',
    'Deutsche Bank AG',
    'Dubai Islamic Bank Pakistan Limited',
    'Faysal Bank Limited',
    'First Women Bank Limited',
    'Habib Bank Limited',
    'Habib Metropolitan Bank Limited',
    'Industrial and Commercial Bank of China Limited',
    'JS Bank Limited',
    'MCB Bank Limited',
    'MCB Islamic Bank Limited',
    'Meezan Bank Limited',
    'National Bank of Pakistan',
    'Sindh Bank Limited',
    'Soneri Bank Limited',
    'Standard Chartered Bank (Pakistan) Limited',
    'The Bank of Khyber',
    'The Bank of Punjab',
    'United Bank Limited',
    'Zarai Taraqiati Bank Limited',
]


class Command(BaseCommand):
    help = 'Reset the ZSP production database to a clean handover state.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Required safety flag. Without this flag the command refuses to run.',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('Refusing to reset data without --confirm.')

        admin_password = os.environ.get('RESET_ZSP_ADMIN_PASSWORD')
        client_password = os.environ.get('RESET_ZSP_CLIENT_PASSWORD')
        if not admin_password or not client_password:
            raise CommandError('RESET_ZSP_ADMIN_PASSWORD and RESET_ZSP_CLIENT_PASSWORD are required.')

        with transaction.atomic():
            self._purge_operational_data()
            admin = self._upsert_admin(admin_password)
            client = self._upsert_client(client_password)
            self._clean_demo_dropdown_options()
            self._ensure_finance_defaults(admin)
            self._reassign_preserved_configuration(admin)
            self._purge_dummy_users(keep_user_ids={admin.id, client.id})

        self.stdout.write(self.style.SUCCESS('ZSP production data reset complete.'))

    def _purge_operational_data(self):
        GatePassLine.objects.all().delete()
        GatePass.objects.all().delete()
        ChequeSettlementAllocation.objects.all().delete()
        ChequeStatusHistory.objects.all().delete()
        CustomerLedgerEntry.objects.all().delete()
        Cheque.objects.all().delete()
        AuctionSaleLine.objects.all().delete()
        AuctionSale.objects.all().delete()
        InventoryBatch.objects.all().delete()
        ContainerItem.objects.filter(parent_item__isnull=False).delete()
        ContainerItem.objects.filter(parent_item__isnull=True).delete()
        PartInventory.objects.all().delete()
        Container.objects.all().delete()
        Customer.objects.all().delete()
        AuditLog.objects.all().delete()

    def _upsert_admin(self, password):
        admin, _ = User.objects.get_or_create(username=PERMANENT_ADMIN_USERNAME)
        admin.first_name = 'Ahsan'
        admin.last_name = 'Toufiq'
        admin.email = ''
        admin.is_active = True
        admin.is_staff = True
        admin.is_superuser = True
        admin.set_password(password)
        admin.save()
        enforce_permanent_admin(admin)
        return admin

    def _upsert_client(self, password):
        client, _ = User.objects.get_or_create(username='syed.zulfiqar')
        client.first_name = 'Syed'
        client.last_name = 'Zulfiqar'
        client.email = ''
        client.is_active = True
        client.is_staff = False
        client.is_superuser = False
        client.set_password(password)
        client.save()
        permissions = {tab: AccessLevel.FULL for tab in sorted(ALL_TABS)}
        permissions['users'] = AccessLevel.NONE
        UserProfile.objects.update_or_create(
            user=client,
            defaults={'tab_permissions': permissions, 'allowed_tabs': []},
        )
        return client

    def _purge_dummy_users(self, *, keep_user_ids):
        UserProfile.objects.exclude(user_id__in=keep_user_ids).delete()
        User.objects.exclude(id__in=keep_user_ids).delete()

    def _clean_demo_dropdown_options(self):
        DropdownOption.objects.filter(group=DropdownOption.Group.PART_NAME).delete()

    def _ensure_finance_defaults(self, admin):
        status_defaults = [
            ('Pending', ChequeStatus.BalanceEffect.NONE),
            ('Cleared', ChequeStatus.BalanceEffect.SETTLES_BALANCE),
            ('Settled', ChequeStatus.BalanceEffect.SETTLES_BALANCE),
            ('Settled by Cash', ChequeStatus.BalanceEffect.SETTLES_BALANCE),
            ('Bounced', ChequeStatus.BalanceEffect.REVERSES_SETTLEMENT),
        ]
        for name, effect in status_defaults:
            ChequeStatus.objects.update_or_create(
                name=name,
                defaults={
                    'balance_effect': effect,
                    'is_system': True,
                    'is_active': True,
                    'updated_by': admin,
                    'created_by': admin,
                },
            )

        for group, labels in {
            DropdownOption.Group.BANK: PAKISTAN_BANKS,
            DropdownOption.Group.ITEM_UNIT: ['piece', 'set', 'pair', 'kg', 'box'],
            DropdownOption.Group.ITEM_CATEGORY: ['Body parts', 'Electrical', 'Engine', 'Interior', 'Lights', 'Suspension', 'Transmission'],
        }.items():
            for index, label in enumerate(labels):
                DropdownOption.objects.update_or_create(
                    group=group,
                    label=label,
                    defaults={'is_system': True, 'is_active': True, 'sort_order': index, 'updated_by': admin, 'created_by': admin},
                )

    def _reassign_preserved_configuration(self, admin):
        DropdownOption.objects.all().update(created_by=admin, updated_by=admin)
        ChequeStatus.objects.all().update(created_by=admin, updated_by=admin)
