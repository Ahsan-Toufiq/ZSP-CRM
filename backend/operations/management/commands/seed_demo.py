from decimal import Decimal
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, full_tab_permissions
from catalog.models import DropdownOption
from finance.models import Cheque, ChequeStatus
from finance.services import change_cheque_status, create_cheque
from operations.models import AuctionSale, Container, ContainerItem, Customer, PartInventory
from operations.services import apply_container_inventory_delta, create_auction_sale


class Command(BaseCommand):
    help = 'Seed local demo data for Digi7 ZSP testing.'

    def handle(self, *args, **options):
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': '',
                'first_name': 'Digi7',
                'last_name': 'Admin',
                'is_staff': True,
                'is_superuser': True,
            },
        )
        if created:
            admin.set_password('Admin@12345')
            admin.save()
        UserProfile.objects.update_or_create(
            user=admin,
            defaults={'tab_permissions': full_tab_permissions(), 'allowed_tabs': []},
        )

        demo_users = [
            ('operator', 'Operations', 'User', 'Operator@12345', {'dashboard': AccessLevel.VIEW, 'customers': AccessLevel.FULL, 'containers': AccessLevel.FULL, 'sales': AccessLevel.FULL}),
            ('finance', 'Finance', 'User', 'Finance@12345', {'dashboard': AccessLevel.VIEW, 'customers': AccessLevel.VIEW, 'cheques': AccessLevel.FULL}),
            ('viewer', 'Read Only', 'User', 'Viewer@12345', {'dashboard': AccessLevel.VIEW, 'customers': AccessLevel.VIEW, 'containers': AccessLevel.VIEW, 'sales': AccessLevel.VIEW, 'cheques': AccessLevel.VIEW}),
        ]
        for username, first_name, last_name, password, permissions in demo_users:
            user, user_created = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first_name, 'last_name': last_name, 'email': ''},
            )
            if user_created:
                user.set_password(password)
                user.save()
            normalized = {tab: AccessLevel.NONE for tab in full_tab_permissions()}
            normalized.update(permissions)
            UserProfile.objects.update_or_create(
                user=user,
                defaults={'tab_permissions': normalized, 'allowed_tabs': []},
            )

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
            ('ZSP-CNT-001', 'Japan', 'Osaka Auto Exports', 18, 'Engine, lights, and mixed body parts.', '385000.00'),
            ('ZSP-CNT-002', 'UAE', 'Sharjah Parts Yard', 12, 'Body panels and mirrors.', '270000.00'),
            ('ZSP-CNT-003', 'Thailand', 'Bangkok Auction Supply', 7, 'Suspension and electrical lots.', '225000.00'),
            ('ZSP-CNT-004', 'Malaysia', 'Penang Dismantlers', 2, 'Fresh receiving container.', '165000.00'),
        ]
        containers = {}
        for reference, origin, supplier, days_ago, notes, added_cost in container_specs:
            container, _ = Container.objects.update_or_create(
                reference=reference,
                defaults={
                    'origin_country': origin,
                    'supplier_name': supplier,
                    'arrival_date': today - timedelta(days=days_ago),
                    'status': Container.Status.READY_FOR_AUCTION if reference != 'ZSP-CNT-004' else Container.Status.RECEIVING,
                    'manifest_notes': notes,
                    'added_cost': Decimal(added_cost),
                    'created_by': admin,
                    'updated_by': admin,
                },
            )
            containers[reference] = container

        item_specs = [
            ('ZSP-CNT-001', 'LOT-001', 'Toyota headlight pair', 'TY-HL-01', 'Lights', 4, 'pair', '18000.00'),
            ('ZSP-CNT-001', 'LOT-002', 'Honda front bumper', 'HN-BM-02', 'Body parts', 3, 'piece', '24000.00'),
            ('ZSP-CNT-001', 'LOT-003', 'Nissan alternator', 'NS-ALT-03', 'Electrical', 5, 'piece', '30000.00'),
            ('ZSP-CNT-001', 'LOT-004', 'Mazda side mirror', 'MZ-MR-04', 'Body parts', 8, 'piece', '9000.00'),
            ('ZSP-CNT-001', 'LOT-005', 'Suzuki tail light', 'SZ-TL-05', 'Lights', 6, 'piece', '11000.00'),
            ('ZSP-CNT-001', 'LOT-006', 'Fuel pump', 'FP-ASSY', 'Engine', 4, 'piece', '26000.00'),
            ('ZSP-CNT-002', 'LOT-101', 'Toyota Prius engine assembly', 'TY-ENG-PR', 'Engine', 2, 'piece', '240000.00'),
            ('ZSP-CNT-002', 'LOT-102', 'Honda Vezel transmission', 'HN-TR-VZ', 'Transmission', 2, 'piece', '190000.00'),
            ('ZSP-CNT-002', 'LOT-103', 'Daihatsu Mira door set', 'DH-DR-MR', 'Body parts', 4, 'set', '65000.00'),
            ('ZSP-CNT-002', 'LOT-104', 'Assorted clips and brackets', 'MIX-CLIP', 'Body parts', 30, 'box', '12000.00'),
            ('ZSP-CNT-002', 'LOT-105', 'Toyota headlight pair', 'TY-HL-01', 'Lights', 2, 'pair', '22000.00'),
            ('ZSP-CNT-002', 'LOT-106', 'Fuel pump', 'FP-ASSY', 'Electrical', 3, 'piece', '29500.00'),
            ('ZSP-CNT-003', 'LOT-201', 'Toyota Aqua ABS pump', 'TY-ABS-AQ', 'Electrical', 3, 'piece', '42000.00'),
            ('ZSP-CNT-003', 'LOT-202', 'Suzuki Swift shock set', 'SZ-SHK-SW', 'Suspension', 5, 'set', '28000.00'),
            ('ZSP-CNT-003', 'LOT-203', 'Nissan Note radiator', 'NS-RAD-NT', 'Engine', 4, 'piece', '22000.00'),
            ('ZSP-CNT-003', 'LOT-204', 'Toyota headlight pair', 'TY-HL-01', 'Exterior', 3, 'pair', '25000.00'),
            ('ZSP-CNT-003', 'LOT-205', 'Fuel pump', 'FP-ASSY', 'Engine', 2, 'piece', '31000.00'),
            ('ZSP-CNT-004', 'LOT-301', 'Unsorted dashboard electronics', 'MIX-DASH', 'Electrical', 12, 'box', '15000.00'),
            ('ZSP-CNT-004', 'LOT-302', 'Damaged bumper bundle', 'MIX-BMP-DMG', 'Body parts', 7, 'piece', '6000.00'),
            ('ZSP-CNT-004', 'LOT-303', 'Toyota headlight pair', 'TY-HL-01', 'Lights', 1, 'pair', '26000.00'),
        ]
        demo_part_pool = [
            ('Door handle set', 'DH-HND', 'Body parts', 12, 'set', '8500.00'),
            ('Fuel pump', 'FP-ASSY', 'Engine', 5, 'piece', '26000.00'),
            ('Bonnet hinge pair', 'BN-HNG', 'Body parts', 6, 'pair', '7000.00'),
            ('Rear bumper garnish', 'RB-GRN', 'Body parts', 9, 'piece', '11500.00'),
            ('Power window switch', 'PW-SW', 'Electrical', 14, 'piece', '6500.00'),
            ('AC compressor', 'AC-CMP', 'Engine', 4, 'piece', '42000.00'),
            ('Steering rack', 'ST-RCK', 'Suspension', 3, 'piece', '52000.00'),
            ('Tailgate lock', 'TG-LCK', 'Body parts', 10, 'piece', '7600.00'),
            ('Side fender', 'SD-FND', 'Body parts', 7, 'piece', '15500.00'),
            ('Throttle body', 'TH-BDY', 'Engine', 5, 'piece', '33000.00'),
            ('Ignition coil pack', 'IG-COIL', 'Electrical', 18, 'piece', '5200.00'),
            ('Brake caliper pair', 'BR-CAL', 'Suspension', 5, 'pair', '21000.00'),
            ('Wiper motor', 'WP-MTR', 'Electrical', 8, 'piece', '10500.00'),
            ('Radiator fan', 'RD-FAN', 'Engine', 6, 'piece', '18500.00'),
            ('Dashboard vent set', 'DS-VENT', 'Interior', 11, 'set', '4800.00'),
        ]
        existing_counts = {}
        for container_ref, *_ in item_specs:
            existing_counts[container_ref] = existing_counts.get(container_ref, 0) + 1
        for container_ref in containers:
            needed = max(15 - existing_counts.get(container_ref, 0), 0)
            for offset in range(needed):
                name, number, category, quantity, unit, raw_cost = demo_part_pool[offset % len(demo_part_pool)]
                lot_prefix = container_ref.rsplit('-', 1)[-1]
                item_specs.append((
                    container_ref,
                    f'LOT-{lot_prefix}-{offset + 900}',
                    f'{name} {lot_prefix}-{offset + 1}',
                    f'{number}-{lot_prefix}-{offset + 1}',
                    category,
                    quantity,
                    unit,
                    raw_cost,
                ))
        items = {}
        for container_ref, lot, name, part_number, category, quantity, unit, raw_cost in item_specs:
            raw_unit_cost = Decimal(raw_cost).quantize(Decimal('0.01'))
            item, item_created = ContainerItem.objects.get_or_create(
                container=containers[container_ref],
                lot_number=lot,
                defaults={
                    'part_name': name,
                    'part_number': part_number,
                    'category': category,
                    'quantity': quantity,
                    'unit': unit,
                    'raw_unit_cost': raw_unit_cost,
                    'created_by': admin,
                    'updated_by': admin,
                },
            )
            if not item_created:
                try:
                    with transaction.atomic():
                        before = {
                            'container_item_id': item.id,
                            'part_name': item.part_name,
                            'part_number': item.part_number or '',
                            'category': item.category or '',
                            'unit': item.unit or 'piece',
                            'quantity': item.quantity,
                            'raw_unit_cost': item.raw_unit_cost,
                            'description': item.description or '',
                        }
                        item.part_name = name
                        item.part_number = part_number
                        item.category = category
                        item.quantity = quantity
                        item.unit = unit
                        item.raw_unit_cost = raw_unit_cost
                        item.updated_by = admin
                        item.save(update_fields=[
                            'part_name', 'part_number', 'category', 'quantity',
                            'unit', 'raw_unit_cost', 'updated_by', 'updated_at',
                        ])
                        apply_container_inventory_delta(user=admin, before=before, after=item)
                except ValidationError:
                    item.refresh_from_db()
                    item.raw_unit_cost = raw_unit_cost
                    item.updated_by = admin
                    item.save(update_fields=['raw_unit_cost', 'updated_by', 'updated_at'])
            if item_created:
                with transaction.atomic():
                    apply_container_inventory_delta(user=admin, after=item)
            items[lot] = item
        parts = {
            lot: PartInventory.objects.filter(
                part_name=item.part_name,
                part_number=item.part_number or '',
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
                        'inventory_batch': items[lot].inventory_batch,
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

        expired_cheques = [
            (
                'ZSP-CHQ-EXP-001',
                customers['Lahore Spare Traders'],
                'United Bank Limited',
                'Lahore Spare Traders',
                Decimal('87500.00'),
                today - timedelta(days=75),
                today - timedelta(days=14),
            ),
            (
                'ZSP-CHQ-EXP-002',
                customers['Rawalpindi Autos'],
                'MCB Bank Limited',
                'Rawalpindi Autos',
                Decimal('42000.00'),
                today - timedelta(days=63),
                today - timedelta(days=7),
            ),
            (
                'ZSP-CHQ-EXP-003',
                customers['Karachi Motor House'],
                'Bank AL Habib Limited',
                'Karachi Motor House',
                Decimal('118000.00'),
                today - timedelta(days=90),
                today - timedelta(days=22),
            ),
        ]
        for cheque_number, customer, bank_name, name_on_cheque, amount, cheque_date, expiry_date in expired_cheques:
            if Cheque.objects.filter(cheque_number=cheque_number, bank_name=bank_name).exists():
                continue
            create_cheque(
                user=admin,
                cheque_number=cheque_number,
                customer=customer,
                name_on_cheque=name_on_cheque,
                bank_name=bank_name,
                branch_name='Demo branch',
                account_title=name_on_cheque,
                amount=amount,
                cheque_date=cheque_date,
                expiry_date=expiry_date,
                received_date=cheque_date,
                status=statuses['Pending'],
                notes='Seeded expired pending cheque for red highlight testing.',
            )

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
                'Door handle set',
                'Fuel pump',
                'AC compressor',
                'Steering rack',
                'Brake caliper pair',
                'Radiator fan',
            ],
            DropdownOption.Group.ITEM_CATEGORY: ['Body parts', 'Electrical', 'Engine', 'Interior', 'Lights', 'Suspension', 'Transmission'],
            DropdownOption.Group.ITEM_UNIT: ['piece', 'set', 'pair', 'kg', 'box'],
        }
        for group, labels in option_groups.items():
            for index, label in enumerate(labels):
                DropdownOption.objects.get_or_create(
                    group=group,
                    label=label,
                    defaults={'is_system': True, 'sort_order': index, 'created_by': admin, 'updated_by': admin},
                )
