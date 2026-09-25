from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import UserProfile
from audit.models import AuditLog
from catalog.models import DropdownOption
from finance.models import (
    Cheque,
    ChequeSettlementAllocation,
    ChequeStatus,
    ChequeStatusHistory,
    Currency,
    CurrencyCreditor,
    CurrencyCreditorRepayment,
    CurrencyOpeningBalance,
    CurrencyPurchase,
    CurrencySpending,
    CustomerLedgerEntry,
    CustomerPayment,
    CustomerPaymentAllocation,
    CustomerPaymentComponent,
    CustomerPaymentTarget,
)
from operations.models import (
    AuctionSale,
    AuctionSaleLine,
    Container,
    ContainerItem,
    Customer,
    GatePass,
    GatePassLine,
    InventoryBatch,
    PartInventory,
)


CONFIRMATION = 'PURGE-NON-USER-BUSINESS-DATA'


def user_snapshot():
    User = get_user_model()
    user_fields = [field.attname for field in User._meta.concrete_fields]
    return {
        'users': list(User.objects.order_by('pk').values(*user_fields)),
        'profiles': list(UserProfile.objects.order_by('pk').values()),
        'groups': list(
            User.groups.through.objects.order_by('user_id', 'group_id').values('user_id', 'group_id')
        ),
        'permissions': list(
            User.user_permissions.through.objects
            .order_by('user_id', 'permission_id')
            .values('user_id', 'permission_id')
        ),
    }


PURGE_QUERYSETS = (
    ('audit logs', lambda: AuditLog.objects.all()),
    ('gate pass lines', lambda: GatePassLine.objects.all()),
    ('gate passes', lambda: GatePass.objects.all()),
    ('cheque allocations', lambda: ChequeSettlementAllocation.objects.all()),
    ('payment allocations', lambda: CustomerPaymentAllocation.objects.all()),
    ('payment targets', lambda: CustomerPaymentTarget.objects.all()),
    ('customer ledger entries', lambda: CustomerLedgerEntry.objects.all()),
    ('cheque status history', lambda: ChequeStatusHistory.objects.all()),
    ('payment components', lambda: CustomerPaymentComponent.objects.all()),
    ('customer payments', lambda: CustomerPayment.objects.all()),
    ('cheques', lambda: Cheque.objects.all()),
    ('gate pass sale lines', lambda: AuctionSaleLine.objects.all()),
    ('auction sales', lambda: AuctionSale.objects.all()),
    ('inventory batches', lambda: InventoryBatch.objects.all()),
    ('container items', lambda: ContainerItem.objects.all()),
    ('parts inventory', lambda: PartInventory.objects.all()),
    ('containers', lambda: Container.objects.all()),
    ('customers', lambda: Customer.objects.all()),
    ('currency creditor repayments', lambda: CurrencyCreditorRepayment.objects.all()),
    ('currency purchases', lambda: CurrencyPurchase.objects.all()),
    ('currency opening balances', lambda: CurrencyOpeningBalance.objects.all()),
    ('currency spending', lambda: CurrencySpending.objects.all()),
    ('currency creditors', lambda: CurrencyCreditor.objects.all()),
    ('custom currencies', lambda: Currency.objects.filter(is_system=False)),
    ('custom cheque statuses', lambda: ChequeStatus.objects.filter(is_system=False)),
    ('custom dropdown options', lambda: DropdownOption.objects.filter(is_system=False)),
)


def delete_container_items_bottom_up():
    """Delete subparts before their protected parent rows."""
    while ContainerItem.objects.exists():
        leaves = ContainerItem.objects.filter(subparts__isnull=True)
        if not leaves.exists():
            raise CommandError('Container item hierarchy is cyclic. No data was changed.')
        leaves.delete()


class Command(BaseCommand):
    help = 'Purge non-user business data while proving that all users and access profiles remain unchanged.'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='Perform the purge. Without this flag, only a plan is printed.')
        parser.add_argument('--confirm', default='', help=f'Must exactly equal {CONFIRMATION}.')
        parser.add_argument('--expected-user-count', type=int, help='Abort unless the current user count matches this value.')

    def handle(self, *args, **options):
        before = user_snapshot()
        user_count = len(before['users'])
        expected_user_count = options.get('expected_user_count')
        if expected_user_count is not None and user_count != expected_user_count:
            raise CommandError(f'Expected {expected_user_count} users, but found {user_count}. No data was changed.')

        counts = [(label, queryset().count()) for label, queryset in PURGE_QUERYSETS]
        self.stdout.write(f'Protected users: {user_count}')
        self.stdout.write(f'Protected profiles: {len(before["profiles"])}')
        for label, count in counts:
            self.stdout.write(f'{label}: {count}')

        if not options['execute']:
            self.stdout.write(self.style.WARNING('Dry run only. No data was changed.'))
            return
        if options['confirm'] != CONFIRMATION:
            raise CommandError(f'Refusing purge. Pass --confirm {CONFIRMATION}.')

        with transaction.atomic():
            for label, queryset in PURGE_QUERYSETS:
                if label == 'container items':
                    delete_container_items_bottom_up()
                else:
                    queryset().delete()
            after = user_snapshot()
            if after != before:
                raise CommandError('User or access-control data changed during purge. Transaction rolled back.')

        self.stdout.write(self.style.SUCCESS(
            f'Business data purged. Verified {user_count} users and {len(before["profiles"])} profiles unchanged.'
        ))
