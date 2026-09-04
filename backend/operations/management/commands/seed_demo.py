from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.permissions import Roles
from catalog.models import DropdownOption
from finance.models import Cheque, ChequeStatus
from finance.services import change_cheque_status, create_cheque
from operations.models import AuctionSale, Container, ContainerItem, Customer, PartInventory
from operations.services import apply_container_inventory_delta, create_auction_sale


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

        self._seed_operational_demo(admin)

        self.stdout.write(self.style.SUCCESS('Seeded Digi7 ZSP demo data. Login: admin / Admin@12345'))

    def _seed_operational_demo(self, admin):
        today = timezone.localdate()
        statuses = {
            name: ChequeStatus.objects.get_or_create(name=name, defaults={'balance_effect': effect})[0]
            for name, effect in [
                ('Pending', ChequeStatus.BalanceEffect.NONE),
                ('Cleared', ChequeStatus.BalanceEffect.SETTLES_BALANCE),
                ('Settled', ChequeStatus.BalanceEffect.SETTLES_BALANCE),
                ('Settled by Cash', ChequeStatus.BalanceEffect.SETTLES_BALANCE),
                ('Bounced', ChequeStatus.BalanceEffect.REVERSES_SETTLEMENT),
            ]
        }

        customers = {}
        for index, (name, phone, customer_type) in enumerate([
            ('Syed Zulfiqar', '+923000000000', Customer.CustomerType.INDIVIDUAL),
            ('Ahsan Toufiq', '+923001112233', Customer.CustomerType.INDIVIDUAL),
            ('Karachi Motor House', '+922134445566', Customer.CustomerType.BUSINESS),
            ('Lahore Spare Traders', '+924235551177', Customer.CustomerType.BUSINESS),
            ('Rawalpindi Autos', '+92515551188', Customer.CustomerType.BUSINESS),
            ('Bilal Workshop', '+923214567890', Customer.CustomerType.BUSINESS),
            ('No Transaction Demo', '+923339990000', Customer.CustomerType.INDIVIDUAL),
        ]):
            customer = (
                Customer.objects.filter(phone=phone).order_by('created_at').first()
                or Customer.objects.filter(name=name, phone=phone).order_by('created_at').first()
            )
            if customer is None:
                customer = Customer.objects.create(
                    name=name,
                    phone=phone,
                    customer_type=customer_type,
                    address=f'Demo address {index + 1}',
                    notes='Seeded demo customer for testing workflows.',
                    created_by=admin,
                    updated_by=admin,
                )
            customers[name] = customer

        container_specs = [
            ('ZSP-CNT-001', 'Japan', 'Osaka Auto Exports', 18, 'Engine, lights, and mixed body parts.'),
            ('ZSP-CNT-002', 'UAE', 'Sharjah Parts Yard', 12, 'Body panels and mirrors.'),
            ('ZSP-CNT-003', 'Thailand', 'Bangkok Auction Supply', 7, 'Suspension and electrical lots.'),
            ('ZSP-CNT-004', 'Malaysia', 'Penang Dismantlers', 2, 'Fresh receiving container.'),
        ]
        containers = {}
        for reference, origin, supplier, days_ago, notes in container_specs:
            containers[reference] = Container.objects.get_or_create(
                reference=reference,
                defaults={
                    'origin_country': origin,
                    'supplier_name': supplier,
                    'arrival_date': today - timedelta(days=days_ago),
                    'status': Container.Status.READY_FOR_AUCTION if reference != 'ZSP-CNT-004' else Container.Status.RECEIVING,
                    'manifest_notes': notes,
                    'created_by': admin,
                    'updated_by': admin,
                },
            )[0]

        item_specs = [
            ('ZSP-CNT-001', 'LOT-001', 'Toyota headlight pair', 'TY-HL-01', 'Lights', 4, 'pair', 'Used', '18000.00'),
            ('ZSP-CNT-001', 'LOT-002', 'Honda front bumper', 'HN-BM-02', 'Body parts', 3, 'piece', 'Used', '24000.00'),
            ('ZSP-CNT-001', 'LOT-003', 'Nissan alternator', 'NS-ALT-03', 'Electrical', 5, 'piece', 'Used', '30000.00'),
            ('ZSP-CNT-001', 'LOT-004', 'Mazda side mirror', 'MZ-MR-04', 'Body parts', 8, 'piece', 'Used', '9000.00'),
            ('ZSP-CNT-001', 'LOT-005', 'Suzuki tail light', 'SZ-TL-05', 'Lights', 6, 'piece', 'Used', '11000.00'),
            ('ZSP-CNT-002', 'LOT-101', 'Toyota Prius engine assembly', 'TY-ENG-PR', 'Engine', 2, 'piece', 'Used', '240000.00'),
            ('ZSP-CNT-002', 'LOT-102', 'Honda Vezel transmission', 'HN-TR-VZ', 'Transmission', 2, 'piece', 'Used', '190000.00'),
            ('ZSP-CNT-002', 'LOT-103', 'Daihatsu Mira door set', 'DH-DR-MR', 'Body parts', 4, 'set', 'Used', '65000.00'),
            ('ZSP-CNT-002', 'LOT-104', 'Assorted clips and brackets', 'MIX-CLIP', 'Body parts', 30, 'box', 'Used', '12000.00'),
            ('ZSP-CNT-003', 'LOT-201', 'Toyota Aqua ABS pump', 'TY-ABS-AQ', 'Electrical', 3, 'piece', 'Used', '42000.00'),
            ('ZSP-CNT-003', 'LOT-202', 'Suzuki Swift shock set', 'SZ-SHK-SW', 'Suspension', 5, 'set', 'Used', '28000.00'),
            ('ZSP-CNT-003', 'LOT-203', 'Nissan Note radiator', 'NS-RAD-NT', 'Engine', 4, 'piece', 'Used', '22000.00'),
            ('ZSP-CNT-004', 'LOT-301', 'Unsorted dashboard electronics', 'MIX-DASH', 'Electrical', 12, 'box', 'Unknown', '15000.00'),
            ('ZSP-CNT-004', 'LOT-302', 'Damaged bumper bundle', 'MIX-BMP-DMG', 'Body parts', 7, 'piece', 'Damaged', '6000.00'),
        ]
        items = {}
        for container_ref, lot, name, part_number, category, quantity, unit, condition, reserve in item_specs:
            item, item_created = ContainerItem.objects.get_or_create(
                container=containers[container_ref],
                lot_number=lot,
                defaults={
                    'part_name': name,
                    'part_number': part_number,
                    'category': category,
                    'condition': condition,
                    'quantity': quantity,
                    'unit': unit,
                    'reserve_price': Decimal(reserve),
                    'created_by': admin,
                    'updated_by': admin,
                },
            )
            if not item_created and item.quantity < quantity:
                before = {
                    'part_name': item.part_name,
                    'part_number': item.part_number or '',
                    'category': item.category or '',
                    'condition': item.condition or '',
                    'unit': item.unit or 'piece',
                    'quantity': item.quantity,
                    'reserve_price': item.reserve_price,
                    'description': item.description or '',
                }
                item.quantity = quantity
                item.updated_by = admin
                item.save(update_fields=['quantity', 'updated_by', 'updated_at'])
                apply_container_inventory_delta(user=admin, before=before, after=item)
            if item_created:
                apply_container_inventory_delta(user=admin, after=item)
            items[lot] = item
        parts = {
            lot: PartInventory.objects.filter(
                part_name=item.part_name,
                part_number=item.part_number or '',
                category=item.category or '',
                condition=item.condition or '',
                unit=item.unit or 'piece',
            ).first()
            for lot, item in items.items()
        }

        sale_specs = [
            (
                'Demo sale: Ahsan split cheque balance',
                today - timedelta(days=10),
                AuctionSale.PaymentType.CREDIT,
                customers['Ahsan Toufiq'],
                [('LOT-001', 1, '22000.00'), ('LOT-004', 2, '9500.00')],
            ),
            (
                'Demo sale: Karachi cheque generated with sale',
                today - timedelta(days=8),
                AuctionSale.PaymentType.CHEQUE,
                customers['Karachi Motor House'],
                [('LOT-101', 1, '275000.00')],
            ),
            (
                'Demo sale: Cash walk-in no customer balance',
                today - timedelta(days=6),
                AuctionSale.PaymentType.CASH,
                None,
                [('LOT-005', 1, '13000.00'), ('LOT-104', 5, '1500.00')],
            ),
            (
                'Demo sale: Lahore outstanding credit',
                today - timedelta(days=5),
                AuctionSale.PaymentType.CREDIT,
                customers['Lahore Spare Traders'],
                [('LOT-102', 1, '215000.00'), ('LOT-201', 1, '46000.00')],
            ),
            (
                'Demo sale: Rawalpindi partial stock',
                today - timedelta(days=3),
                AuctionSale.PaymentType.CREDIT,
                customers['Rawalpindi Autos'],
                [('LOT-202', 2, '31000.00')],
            ),
        ]
        for marker, sale_date, payment_type, customer, lines in sale_specs:
            if AuctionSale.objects.filter(notes=marker).exists():
                continue
            cheque = None
            if payment_type == AuctionSale.PaymentType.CHEQUE:
                cheque = {
                    'cheque_number': 'ZSP-CHQ-SALE-001',
                    'name_on_cheque': customer.name,
                    'bank_name': 'Habib Bank Limited',
                    'branch_name': 'Saddar',
                    'account_title': customer.name,
                    'cheque_date': sale_date,
                    'expiry_date': sale_date + timedelta(days=45),
                    'received_date': sale_date,
                    'notes': 'Seeded cheque generated from auction sale.',
                }
            create_auction_sale(
                user=admin,
                sale_date=sale_date,
                payment_type=payment_type,
                customer=customer,
                notes=marker,
                lines=[
                    {
                        'item': parts[lot],
                        'quantity': quantity,
                        'sold_price': Decimal(price),
                        'notes': 'Seeded sale line.',
                    }
                    for lot, quantity, price in lines
                ],
                cheque=cheque,
                gate_pass={
                    'issued_to_name': customer.name if customer else 'Cash buyer',
                    'issued_to_phone': customer.phone if customer else '',
                    'vehicle_number': 'KHI-7788' if customer else 'WALK-IN',
                    'driver_name': 'Demo driver',
                    'notes': 'Seeded gate pass details.',
                },
            )

        settlement_customer = customers['Ahsan Toufiq']
        if not Cheque.objects.filter(cheque_number='ZSP-CHQ-SETTLE-001', bank_name='Meezan Bank Limited').exists():
            cheque = create_cheque(
                user=admin,
                cheque_number='ZSP-CHQ-SETTLE-001',
                customer=settlement_customer,
                name_on_cheque='Ahsan Toufiq',
                bank_name='Meezan Bank Limited',
                branch_name='Clifton',
                account_title='Ahsan Toufiq',
                amount=Decimal('30000.00'),
                cheque_date=today - timedelta(days=4),
                expiry_date=today + timedelta(days=40),
                received_date=today - timedelta(days=4),
                status=statuses['Pending'],
                notes='Seeded separate cheque that settles oldest balances first.',
            )
            change_cheque_status(user=admin, cheque=cheque, status=statuses['Cleared'])

        if not Cheque.objects.filter(cheque_number='ZSP-CHQ-BOUNCE-001', bank_name='Bank Alfalah Limited').exists():
            bounced_cheque = create_cheque(
                user=admin,
                cheque_number='ZSP-CHQ-BOUNCE-001',
                customer=customers['Bilal Workshop'],
                name_on_cheque='Bilal Workshop',
                bank_name='Bank Alfalah Limited',
                amount=Decimal('48000.00'),
                cheque_date=today - timedelta(days=2),
                expiry_date=today + timedelta(days=35),
                received_date=None,
                status=statuses['Pending'],
                notes='Seeded pending cheque for status testing.',
            )
            change_cheque_status(user=admin, cheque=bounced_cheque, status=statuses['Bounced'])

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
            DropdownOption.Group.PART_NAME: [
                'Toyota headlight pair',
                'Honda front bumper',
                'Nissan alternator',
                'Mazda side mirror',
                'Suzuki tail light',
                'Engine assembly',
                'Transmission',
                'ABS pump',
                'Shock set',
            ],
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
