from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from finance.models import ChequeStatus
from finance.services import create_cheque
from accounts.permissions import Roles
from catalog.models import DropdownOption
from operations.models import AuctionSale, Container, ContainerItem, Customer
from operations.services import create_auction_sale


class Command(BaseCommand):
    help = 'Seed local demo data for Digi7 ZSP testing.'

    def handle(self, *args, **options):
        role_groups = {role: Group.objects.get_or_create(name=role)[0] for role in [
            Roles.ADMIN,
            Roles.OPERATIONS,
            Roles.FINANCE,
            Roles.GATEKEEPER,
        ]}

        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@digi7.local',
                'first_name': 'Digi7',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            admin.set_password('Admin@12345')
            admin.save()
        admin.groups.add(role_groups[Roles.ADMIN])

        demo_users = [
            ('operator', 'Operations', 'User', 'Operator@12345', Roles.OPERATIONS),
            ('finance', 'Finance', 'User', 'Finance@12345', Roles.FINANCE),
            ('gatekeeper', 'Gatekeeper', 'User', 'Gatekeeper@12345', Roles.GATEKEEPER),
        ]
        for username, first_name, last_name, password, role in demo_users:
            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first_name, 'last_name': last_name, 'email': f'{username}@digi7.local'},
            )
            if user_created:
                user.set_password(password)
                user.save()
            user.groups.add(role_groups[role])

        self._seed_dropdown_options(admin)

        customer, _ = Customer.objects.get_or_create(
            name='Syed Zulfiqar',
            defaults={'phone': '+923000000000', 'customer_type': Customer.CustomerType.INDIVIDUAL},
        )

        container, _ = Container.objects.get_or_create(
            reference='ZSP-CNT-001',
            defaults={
                'origin_country': 'Japan',
                'supplier_name': 'Overseas supplier',
                'arrival_date': timezone.localdate(),
                'status': Container.Status.READY_FOR_AUCTION,
                'manifest_notes': 'Demo manifest for local verification.',
            },
        )

        item_specs = [
            ('LOT-001', 'Toyota headlight', 'TY-HL-01', 'Lights', Decimal('18000.00')),
            ('LOT-002', 'Honda bumper', 'HN-BM-02', 'Body parts', Decimal('24000.00')),
            ('LOT-003', 'Nissan alternator', 'NS-ALT-03', 'Electrical', Decimal('30000.00')),
            ('LOT-004', 'Mazda side mirror', 'MZ-MR-04', 'Body parts', Decimal('9000.00')),
            ('LOT-005', 'Suzuki tail light', 'SZ-TL-05', 'Lights', Decimal('11000.00')),
        ]
        for lot, name, part_number, category, reserve in item_specs:
            ContainerItem.objects.get_or_create(
                container=container,
                lot_number=lot,
                defaults={
                    'part_name': name,
                    'part_number': part_number,
                    'category': category,
                    'condition': ContainerItem.Condition.USED,
                    'reserve_price': reserve,
                },
            )

        if not AuctionSale.objects.exists():
            sale_item = ContainerItem.objects.get(container=container, lot_number='LOT-001')
            create_auction_sale(
                user=admin,
                sale_date=timezone.localdate(),
                payment_type=AuctionSale.PaymentType.CREDIT,
                customer=customer,
                lines=[{'item': sale_item, 'sold_price': Decimal('22000.00')}],
            )

        pending_status = ChequeStatus.objects.get_or_create(name='Pending', defaults={'balance_effect': ChequeStatus.BalanceEffect.NONE})[0]
        if not customer.cheques.exists():
            create_cheque(
                user=admin,
                cheque_number='ZSP-CHQ-001',
                customer=customer,
                name_on_cheque='Syed Zulfiqar',
                bank_name='HBL',
                amount=Decimal('22000.00'),
                cheque_date=timezone.localdate(),
                expiry_date=timezone.localdate(),
                received_date=None,
                status=pending_status,
            )

        self.stdout.write(self.style.SUCCESS('Seeded Digi7 ZSP demo data. Login: admin / Admin@12345'))

    def _seed_dropdown_options(self, admin):
        banks = [
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
        option_groups = {
            DropdownOption.Group.BANK: banks,
            DropdownOption.Group.ITEM_CATEGORY: ['Body parts', 'Electrical', 'Engine', 'Lights', 'Suspension', 'Transmission'],
            DropdownOption.Group.ITEM_CONDITION: ['Unknown', 'Used', 'New', 'Damaged'],
            DropdownOption.Group.ITEM_UNIT: ['piece', 'set', 'pair', 'kg', 'box'],
        }
        for group, labels in option_groups.items():
            for index, label in enumerate(labels):
                DropdownOption.objects.get_or_create(
                    group=group,
                    label=label,
                    defaults={'is_system': True, 'sort_order': index, 'created_by': admin, 'updated_by': admin},
                )
