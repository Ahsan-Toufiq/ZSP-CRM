from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from catalog.models import DropdownOption
from finance.models import Cheque, ChequeStatus, CustomerLedgerEntry
from finance.services import change_cheque_status
from operations.models import AuctionSale, Container, ContainerItem, GatePassLine, InventoryBatch, PartInventory
from operations.services import available_quantity_for_batch, available_quantity_for_item, create_auction_sale, issue_gate_pass, mark_gate_pass_printed, recalculate_container_net_costs, update_auction_sale


@pytest.fixture
def user(db):
    return User.objects.create_user(username='operator', password='strong-password')


@pytest.fixture
def customer(db):
    from operations.models import Customer

    return Customer.objects.create(name='Zulfiqar Autos', phone='+923000000000')


@pytest.fixture
def item(db):
    return PartInventory.objects.create(part_name='Headlight', quantity=1, unit='piece')


@pytest.fixture
def second_item(db):
    return PartInventory.objects.create(part_name='Bumper', quantity=1, unit='piece')


def make_batch(item, quantity=None, raw_unit_cost=Decimal('5000.00'), source_label='Test batch'):
    return InventoryBatch.objects.create(
        item=item,
        quantity=quantity if quantity is not None else item.quantity,
        raw_unit_cost=raw_unit_cost,
        source_label=source_label,
    )


@pytest.mark.django_db
def test_credit_sale_marks_item_sold_and_posts_customer_balance(user, customer, item):
    batch = make_batch(item)
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
    )

    item.refresh_from_db()
    assert sale.total_amount == Decimal('15000.00')
    assert available_quantity_for_item(item) == 0
    assert CustomerLedgerEntry.objects.get(customer=customer).debit == Decimal('15000.00')


@pytest.mark.django_db
def test_non_cash_sale_requires_customer(user, item):
    batch = make_batch(item)
    with pytest.raises(ValidationError):
        create_auction_sale(
            user=user,
            sale_date=timezone.localdate(),
            payment_type=AuctionSale.PaymentType.CREDIT,
            customer=None,
            lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
        )


@pytest.mark.django_db
def test_cash_sale_does_not_enter_customer_balance(user, item):
    batch = make_batch(item)
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CASH,
        customer=None,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
    )

    assert sale.customer is None
    assert CustomerLedgerEntry.objects.filter(sale=sale).count() == 0


@pytest.mark.django_db
def test_sold_item_cannot_be_sold_again(user, customer, item):
    batch = make_batch(item)
    create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
    )

    with pytest.raises(ValidationError):
        create_auction_sale(
            user=user,
            sale_date=timezone.localdate(),
            payment_type=AuctionSale.PaymentType.CREDIT,
            customer=customer,
            lines=[{'inventory_batch': batch, 'sold_price': Decimal('16000.00')}],
        )


@pytest.mark.django_db
def test_sale_can_sell_partial_container_quantity(user, customer, item):
    item.quantity = 3
    item.save(update_fields=['quantity'])
    batch = make_batch(item, quantity=3)

    first_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'quantity': 2, 'sold_price': Decimal('5000.00')}],
    )

    item.refresh_from_db()
    assert first_sale.total_amount == Decimal('10000.00')
    assert available_quantity_for_item(item) == 1

    second_sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('6000.00')}],
    )

    item.refresh_from_db()
    assert second_sale.total_amount == Decimal('6000.00')
    assert available_quantity_for_item(item) == 0


@pytest.mark.django_db
def test_sale_selects_specific_cost_batch_for_same_part(user, customer, item):
    item.quantity = 4
    item.save(update_fields=['quantity'])
    first_batch = make_batch(item, quantity=2, raw_unit_cost=Decimal('5000.00'), source_label='ZSP-CNT-001')
    second_batch = make_batch(item, quantity=2, raw_unit_cost=Decimal('7000.00'), source_label='ZSP-CNT-002')

    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': second_batch, 'quantity': 1, 'sold_price': Decimal('12000.00')}],
    )
    line = sale.lines.get()

    assert line.item == item
    assert line.inventory_batch == second_batch
    assert line.raw_unit_cost_snapshot == Decimal('7000.00')
    assert available_quantity_for_item(item) == 3
    assert first_batch.sale_lines.count() == 0


@pytest.mark.django_db
def test_sale_auto_creates_gate_pass_without_release_verification(user, customer, item):
    batch = make_batch(item)
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
    )
    sale_line = sale.lines.get()
    gate_pass = sale.gate_pass

    same_gate_pass = issue_gate_pass(
        user=user,
        sale_line_ids=[sale_line.id],
        issued_to_name='Syed Zulfiqar',
        vehicle_number='ABC-123',
    )

    item.refresh_from_db()
    assert same_gate_pass.id == gate_pass.id
    assert available_quantity_for_item(item) == 0
    assert GatePassLine.objects.filter(sale_line=sale_line).count() == 1

    mark_gate_pass_printed(user=user, gate_pass=gate_pass)
    gate_pass.refresh_from_db()
    assert gate_pass.print_status == gate_pass.PrintStatus.PRINTED


@pytest.mark.django_db
def test_cheque_sale_creates_cheque_and_balance_settles_only_when_cleared(user, customer, item):
    batch = make_batch(item)
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CHEQUE,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
        cheque={
            'cheque_number': 'CHQ-SALE-001',
            'name_on_cheque': 'Zulfiqar Autos',
            'bank_name': 'HBL',
            'amount': Decimal('15000.00'),
            'cheque_date': timezone.localdate(),
            'expiry_date': timezone.localdate(),
            'received_date': None,
        },
    )

    cheque = Cheque.objects.get(sale=sale)
    assert cheque.status.name == 'Pending'
    assert CustomerLedgerEntry.objects.filter(customer=customer).count() == 1
    assert CustomerLedgerEntry.objects.get(customer=customer).debit == Decimal('15000.00')

    change_cheque_status(user=user, cheque=cheque, status=ChequeStatus.objects.get(name='Cleared'))
    totals = CustomerLedgerEntry.objects.filter(customer=customer)
    assert sum(entry.debit for entry in totals) == Decimal('15000.00')
    assert sum(entry.credit for entry in totals) == Decimal('15000.00')


@pytest.mark.django_db
def test_sale_update_changes_gate_pass_lines_and_resets_print_status(user, customer, item, second_item):
    batch = make_batch(item)
    second_batch = make_batch(second_item)
    sale = create_auction_sale(
        user=user,
        sale_date=timezone.localdate(),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'sold_price': Decimal('15000.00')}],
    )
    gate_pass = sale.gate_pass
    mark_gate_pass_printed(user=user, gate_pass=gate_pass)

    update_auction_sale(
        user=user,
        sale=sale,
        customer=customer,
        lines=[
            {'id': sale.lines.get().id, 'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('16000.00')},
            {'inventory_batch': second_batch, 'quantity': 1, 'sold_price': Decimal('12000.00')},
        ],
    )

    gate_pass.refresh_from_db()
    assert gate_pass.print_status == gate_pass.PrintStatus.NOT_PRINTED
    assert gate_pass.lines.count() == 2
    assert sale.lines.count() == 2


@pytest.mark.django_db
def test_new_item_category_persists_as_dropdown_option(user):
    from operations.serializers import ContainerItemSerializer

    container = Container.objects.create(reference='CNT-OPTION')
    serializer = ContainerItemSerializer(
        data={
            'container': str(container.id),
            'lot_number': 'OPT-1',
            'part_name': 'Custom mirror',
            'category': 'Custom Category',
            'quantity': 1,
            'unit': 'crate',
        },
        context={'request': type('Request', (), {'user': user})()},
    )
    assert serializer.is_valid(), serializer.errors
    serializer.save(created_by=user, updated_by=user)

    assert DropdownOption.objects.filter(group=DropdownOption.Group.ITEM_CATEGORY, label='Custom Category').exists()
    assert DropdownOption.objects.filter(group=DropdownOption.Group.ITEM_UNIT, label='crate').exists()
    assert DropdownOption.objects.filter(group=DropdownOption.Group.PART_NAME, label='Custom mirror').exists()


@pytest.mark.django_db
def test_aggregate_parts_inventory_quantity_is_controlled_by_source_rows(user):
    from operations.serializers import ContainerItemSerializer, PartInventorySerializer

    container = Container.objects.create(reference='CNT-DELTA')
    request = type('Request', (), {'user': user})()
    serializer = ContainerItemSerializer(
        data={
            'container': str(container.id),
            'part_name': 'Split engine assembly',
            'quantity': 2,
            'unit': 'piece',
        },
        context={'request': request},
    )
    assert serializer.is_valid(), serializer.errors
    manifest_item = serializer.save(created_by=user, updated_by=user)

    part = PartInventory.objects.get(part_name='Split engine assembly')
    assert part.quantity == 2

    part_serializer = PartInventorySerializer(
        part,
        data={'quantity': 5},
        partial=True,
        context={'request': request},
    )
    assert not part_serializer.is_valid()
    assert 'quantity' in part_serializer.errors

    manifest_item.refresh_from_db()
    part.refresh_from_db()
    assert manifest_item.quantity == 2
    assert part.quantity == 2


@pytest.mark.django_db
def test_container_item_with_same_part_identity_accumulates_existing_manifest_and_inventory(user):
    from operations.serializers import ContainerItemSerializer

    container = Container.objects.create(reference='CNT-MERGE')
    request = type('Request', (), {'user': user})()
    first = ContainerItemSerializer(
        data={
            'container': str(container.id),
            'part_name': 'Fuel pump',
            'part_number': 'FP-ASSY',
            'category': 'Engine',
            'quantity': 2,
            'unit': 'piece',
            'raw_unit_cost': '1000.00',
        },
        context={'request': request},
    )
    assert first.is_valid(), first.errors
    first_item = first.save(created_by=user, updated_by=user)

    second = ContainerItemSerializer(
        data={
            'container': str(container.id),
            'part_name': 'Fuel pump',
            'part_number': 'FP-ASSY',
            'category': 'Engine',
            'quantity': 3,
            'unit': 'piece',
            'raw_unit_cost': '2000.00',
        },
        context={'request': request},
    )
    assert second.is_valid(), second.errors
    merged_item = second.save(created_by=user, updated_by=user)

    first_item.refresh_from_db()
    part = PartInventory.objects.get(part_name='Fuel pump', part_number='FP-ASSY', category='Engine')
    assert merged_item.id == first_item.id
    assert first_item.quantity == 5
    assert first_item.raw_unit_cost == Decimal('1600.00')
    assert part.quantity == 5
    assert part.category == 'Engine'
    assert part.batches.count() == 1
    assert part.batches.get().quantity == 5


@pytest.mark.django_db
def test_same_part_number_with_different_category_is_separate_inventory(user):
    from operations.serializers import ContainerItemSerializer

    container = Container.objects.create(reference='CNT-CAT-ID')
    request = type('Request', (), {'user': user})()
    for category in ['Engine', 'Electrical']:
        serializer = ContainerItemSerializer(
            data={
                'container': str(container.id),
                'part_name': 'Fuel pump',
                'part_number': 'FP-ASSY',
                'category': category,
                'quantity': 2,
                'unit': 'piece',
                'raw_unit_cost': '1000.00',
            },
            context={'request': request},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(created_by=user, updated_by=user)

    assert PartInventory.objects.filter(part_name='Fuel pump', part_number='FP-ASSY').count() == 2
    assert PartInventory.objects.get(part_name='Fuel pump', part_number='FP-ASSY', category='Engine').quantity == 2
    assert PartInventory.objects.get(part_name='Fuel pump', part_number='FP-ASSY', category='Electrical').quantity == 2


@pytest.mark.django_db
def test_direct_parts_inventory_requires_source_container_and_creates_container_source(user):
    from operations.serializers import PartInventorySerializer

    container = Container.objects.create(reference='CNT-DIRECT')
    request = type('Request', (), {'user': user})()
    missing_source = PartInventorySerializer(
        data={
            'part_name': 'Bonnet hinge pair',
            'quantity': 2,
            'unit': 'pair',
        },
        context={'request': request},
    )
    assert not missing_source.is_valid()
    assert 'sources' in missing_source.errors

    serializer = PartInventorySerializer(
        data={
            'part_name': 'Bonnet hinge pair',
            'part_number': 'BN-HNG',
            'category': 'Body parts',
            'quantity': 2,
            'unit': 'pair',
            'source_container': str(container.id),
            'raw_unit_cost': '7000.00',
        },
        context={'request': request},
    )
    assert serializer.is_valid(), serializer.errors
    part = serializer.save(created_by=user, updated_by=user)

    batch = part.batches.get()
    assert batch.container == container
    assert batch.container_item is not None
    assert batch.quantity == 2
    assert batch.raw_unit_cost == Decimal('7000.00')
    assert container.items.count() == 1


@pytest.mark.django_db
def test_blank_part_number_identity_accumulates_by_name_category_and_unit(user):
    from operations.serializers import ContainerItemSerializer

    container = Container.objects.create(reference='CNT-BLANK')
    request = type('Request', (), {'user': user})()
    for _ in range(2):
        serializer = ContainerItemSerializer(
            data={
                'container': str(container.id),
                'part_name': 'Unknown clip set',
                'part_number': '',
                'category': 'Body parts',
                'quantity': 2,
                'unit': 'set',
                'raw_unit_cost': '500.00',
            },
            context={'request': request},
        )
        assert serializer.is_valid(), serializer.errors
        serializer.save(created_by=user, updated_by=user)

    assert ContainerItem.objects.count() == 1
    assert PartInventory.objects.get(part_name='Unknown clip set', part_number='', category='Body parts').quantity == 4


@pytest.mark.django_db
def test_pre_auction_inventory_change_recalculates_all_container_net_costs(user):
    container = Container.objects.create(reference='CNT-REPRICE', status=Container.Status.GODOWN_LOADING, added_cost=Decimal('300.00'))
    first = ContainerItem.objects.create(container=container, part_name='A', quantity=1, raw_unit_cost=Decimal('100.00'), created_by=user, updated_by=user)
    second = ContainerItem.objects.create(container=container, part_name='B', quantity=1, raw_unit_cost=Decimal('200.00'), created_by=user, updated_by=user)

    recalculate_container_net_costs(user=user, container=container)
    first.refresh_from_db()
    second.refresh_from_db()

    assert first.net_unit_cost == Decimal('200.00')
    assert second.net_unit_cost == Decimal('400.00')


@pytest.mark.django_db
def test_ready_container_new_inventory_does_not_reprice_existing_items(user):
    from operations.serializers import ContainerItemSerializer

    container = Container.objects.create(reference='CNT-LOCKED', status=Container.Status.GODOWN_LOADING, added_cost=Decimal('300.00'))
    existing = ContainerItem.objects.create(container=container, part_name='A', quantity=1, raw_unit_cost=Decimal('100.00'), created_by=user, updated_by=user)
    recalculate_container_net_costs(user=user, container=container)
    existing.refresh_from_db()
    locked_cost = existing.net_unit_cost
    container.status = Container.Status.READY_FOR_AUCTION
    container.save(update_fields=['status'])

    request = type('Request', (), {'user': user})()
    serializer = ContainerItemSerializer(
        data={
            'container': str(container.id),
            'part_name': 'B',
            'quantity': 1,
            'unit': 'piece',
            'raw_unit_cost': '500.00',
        },
        context={'request': request},
    )
    assert serializer.is_valid(), serializer.errors
    new_item = serializer.save(created_by=user, updated_by=user)

    existing.refresh_from_db()
    assert existing.net_unit_cost == locked_cost
    assert new_item.net_unit_cost == Decimal('500.00')


@pytest.mark.django_db
def test_subpart_creation_reduces_parent_and_creates_sellable_sources(user):
    from operations.services import create_subparts

    container = Container.objects.create(reference='CNT-SUB', status=Container.Status.READY_FOR_AUCTION, added_cost=Decimal('1000.00'))
    parent_part = PartInventory.objects.create(part_name='Damaged bumper', part_number='D-BMP', category='Body parts', quantity=2, unit='piece')
    parent = ContainerItem.objects.create(
        container=container,
        part_name='Damaged bumper',
        part_number='D-BMP',
        category='Body parts',
        quantity=2,
        unit='piece',
        raw_unit_cost=Decimal('10000.00'),
        net_unit_cost=Decimal('11000.00'),
        created_by=user,
        updated_by=user,
    )
    InventoryBatch.objects.create(item=parent_part, container=container, container_item=parent, quantity=2, raw_unit_cost=parent.raw_unit_cost, net_unit_cost=parent.net_unit_cost)

    created = create_subparts(
        user=user,
        parent_item=parent,
        split_quantity=1,
        subparts=[
            {'part_name': 'Bumper bracket', 'part_number': 'BRKT', 'category': 'Body parts', 'quantity': 2, 'unit': 'piece', 'raw_unit_cost': Decimal('1000.00')},
            {'part_name': 'Bumper grill', 'part_number': 'GRILL', 'category': 'Body parts', 'quantity': 1, 'unit': 'piece', 'raw_unit_cost': Decimal('3000.00')},
        ],
    )

    parent.refresh_from_db()
    assert parent.quantity == 1
    assert len(created) == 2
    assert available_quantity_for_batch(InventoryBatch.objects.get(container_item=parent)) == 1
    assert PartInventory.objects.get(part_name='Bumper bracket', part_number='BRKT', category='Body parts').quantity == 2
