from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from audit.models import AuditLog
from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from finance.models import ChequeStatus, CustomerLedgerEntry
from finance.services import create_cheque
from operations.models import AuctionSale, AuctionSaleLine, ContainerItem, GatePass, GatePassLine, InventoryBatch, PartInventory

MONEY_QUANTUM = Decimal('0.01')


def _number(prefix: str) -> str:
    now = timezone.localtime()
    return f'{prefix}-{now:%Y%m%d-%H%M%S}-{str(timezone.now().timestamp()).replace(".", "")[-5:]}'


def _quantity(line) -> int:
    quantity = int(line.get('quantity') or 1)
    if quantity <= 0:
        raise ValidationError({'lines': 'Quantity must be greater than zero.'})
    return quantity


def _line_total(line) -> Decimal:
    price = Decimal(str(line['sold_price']))
    if price <= 0:
        raise ValidationError({'lines': 'Unit sold price must be greater than zero.'})
    return price * Decimal(_quantity(line))


def _sale_total(lines) -> Decimal:
    return sum((_line_total(line) for line in lines), Decimal('0.00'))


def sold_quantity_for_item(item: PartInventory, *, excluding_sale: AuctionSale | None = None) -> int:
    queryset = AuctionSaleLine.objects.filter(item=item, sale__is_cancelled=False)
    if excluding_sale is not None:
        queryset = queryset.exclude(sale=excluding_sale)
    return int(queryset.aggregate(total=Sum('quantity'))['total'] or 0)


def available_quantity_for_item(item: PartInventory, *, excluding_sale: AuctionSale | None = None) -> int:
    return max(int(item.quantity) - sold_quantity_for_item(item, excluding_sale=excluding_sale), 0)


def sold_quantity_for_batch(batch: InventoryBatch, *, excluding_sale: AuctionSale | None = None) -> int:
    queryset = AuctionSaleLine.objects.filter(inventory_batch=batch, sale__is_cancelled=False)
    if excluding_sale is not None:
        queryset = queryset.exclude(sale=excluding_sale)
    return int(queryset.aggregate(total=Sum('quantity'))['total'] or 0)


def available_quantity_for_batch(batch: InventoryBatch, *, excluding_sale: AuctionSale | None = None) -> int:
    return max(int(batch.quantity) - sold_quantity_for_batch(batch, excluding_sale=excluding_sale), 0)


def net_unit_cost_for_container_item(container_item: ContainerItem) -> Decimal:
    if not container_item.quantity:
        return Decimal('0.00')
    raw_total = Decimal(container_item.raw_unit_cost) * Decimal(container_item.quantity)
    if raw_total <= 0:
        return Decimal(container_item.raw_unit_cost)
    raw_total_expression = ExpressionWrapper(
        F('raw_unit_cost') * F('quantity'),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )
    container_raw_total = (
        ContainerItem.objects
        .filter(container=container_item.container)
        .aggregate(total=Sum(raw_total_expression))['total']
        or Decimal('0.00')
    )
    if container_raw_total <= 0:
        return Decimal(container_item.raw_unit_cost)
    added_share_total = Decimal(container_item.container.added_cost or 0) * (raw_total / container_raw_total)
    return (Decimal(container_item.raw_unit_cost) + (added_share_total / Decimal(container_item.quantity))).quantize(MONEY_QUANTUM)


def net_unit_cost_for_batch(batch: InventoryBatch) -> Decimal:
    if batch.container_item_id:
        return net_unit_cost_for_container_item(batch.container_item)
    return Decimal(batch.raw_unit_cost or 0).quantize(MONEY_QUANTUM)


def merge_category_values(*values) -> str:
    labels = []
    seen = set()
    for value in values:
        for label in str(value or '').split(','):
            cleaned = label.strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                labels.append(cleaned)
                seen.add(key)
    return ', '.join(labels)


def _part_payload(source) -> dict:
    return {
        'part_name': source.part_name,
        'part_number': source.part_number or '',
        'category': source.category or '',
        'unit': source.unit or 'piece',
        'reserve_price': source.reserve_price,
        'description': source.description or '',
    }


def _part_inventory_for_payload(payload: dict) -> PartInventory | None:
    return PartInventory.objects.select_for_update().filter(
        part_name=payload['part_name'],
        part_number=payload['part_number'],
        unit=payload['unit'],
    ).first()


def _sync_container_batch(*, user, container_item: ContainerItem, inventory: PartInventory) -> InventoryBatch:
    batch, _ = InventoryBatch.objects.select_for_update().update_or_create(
        container_item=container_item,
        defaults={
            'item': inventory,
            'container': container_item.container,
            'source_label': container_item.container.reference,
            'quantity': container_item.quantity,
            'raw_unit_cost': container_item.raw_unit_cost,
            'notes': container_item.description or '',
            'updated_by': user,
            'created_by': user,
        },
    )
    return batch


def _delete_or_zero_container_batch(*, user, container_item_id) -> None:
    batch = InventoryBatch.objects.select_for_update(of=('self',)).filter(container_item_id=container_item_id).order_by().first()
    if batch is None:
        return
    sold = sold_quantity_for_batch(batch)
    if sold:
        batch.quantity = sold
        batch.updated_by = user
        batch.save(update_fields=['quantity', 'updated_by', 'updated_at'])
        return
    batch.delete()


def apply_container_inventory_delta(*, user, before: dict | None = None, after: ContainerItem | None = None) -> None:
    if before:
        inventory = _part_inventory_for_payload(before)
        if inventory:
            next_quantity = int(inventory.quantity) - int(before['quantity'])
            sold = sold_quantity_for_item(inventory)
            if next_quantity < sold:
                raise ValidationError({
                    'quantity': f'Cannot reduce parts inventory below {sold} already sold unit(s) for {inventory.part_name}.',
                })
            inventory.quantity = max(next_quantity, 0)
            inventory.updated_by = user
            inventory.save(update_fields=['quantity', 'updated_by', 'updated_at'])
        if before.get('container_item_id'):
            _delete_or_zero_container_batch(user=user, container_item_id=before['container_item_id'])

    if after:
        payload = _part_payload(after)
        inventory = _part_inventory_for_payload(payload)
        if inventory is None:
            inventory = PartInventory.objects.create(
                **payload,
                quantity=after.quantity,
                created_by=user,
                updated_by=user,
            )
        else:
            inventory.quantity = int(inventory.quantity) + int(after.quantity)
            inventory.category = merge_category_values(inventory.category, payload['category'])
            if not inventory.description and payload['description']:
                inventory.description = payload['description']
            if inventory.reserve_price is None and payload['reserve_price'] is not None:
                inventory.reserve_price = payload['reserve_price']
            inventory.updated_by = user
            inventory.save(update_fields=['quantity', 'category', 'description', 'reserve_price', 'updated_by', 'updated_at'])
        _sync_container_batch(user=user, container_item=after, inventory=inventory)


def _manual_batch_for_item(*, user, item: PartInventory, source_container=None, raw_unit_cost=Decimal('0.00')) -> InventoryBatch:
    batch = (
        InventoryBatch.objects
        .select_for_update(of=('self',))
        .filter(
            item=item,
            container=source_container,
            container_item__isnull=True,
            raw_unit_cost=raw_unit_cost,
        )
        .order_by()
        .first()
    )
    if batch is not None:
        return batch
    return InventoryBatch.objects.create(
        item=item,
        container=source_container,
        source_label=source_container.reference if source_container else 'Manual adjustment',
        quantity=0,
        raw_unit_cost=raw_unit_cost,
        created_by=user,
        updated_by=user,
    )


def sync_manual_inventory_batch_delta(
    *,
    user,
    item: PartInventory,
    before_quantity: int = 0,
    source_container=None,
    raw_unit_cost=Decimal('0.00'),
) -> None:
    delta = int(item.quantity) - int(before_quantity)
    if delta == 0:
        return
    batch = _manual_batch_for_item(
        user=user,
        item=item,
        source_container=source_container,
        raw_unit_cost=Decimal(raw_unit_cost or 0).quantize(MONEY_QUANTUM),
    )
    next_quantity = int(batch.quantity) + delta
    sold = sold_quantity_for_batch(batch)
    if next_quantity < sold:
        raise ValidationError({
            'quantity': f'Cannot reduce manual stock below {sold} already sold unit(s) for {item.part_name}.',
        })
    batch.quantity = max(next_quantity, 0)
    batch.updated_by = user
    batch.save(update_fields=['quantity', 'updated_by', 'updated_at'])


def _batch_id(line) -> str:
    batch = line['inventory_batch']
    return str(batch.id if hasattr(batch, 'id') else batch)


def _default_gate_pass_data(sale: AuctionSale) -> dict:
    customer = sale.customer
    return {
        'issued_to_name': customer.name if customer else 'Cash customer',
        'issued_to_phone': customer.phone if customer else '',
        'vehicle_number': '',
        'driver_name': '',
        'notes': '',
    }


def _sync_gate_pass_for_sale(*, user, sale: AuctionSale, gate_pass_data: dict | None = None) -> GatePass:
    data = {**_default_gate_pass_data(sale), **(gate_pass_data or {})}
    try:
        gate_pass = sale.gate_pass
    except GatePass.DoesNotExist:
        gate_pass = GatePass.objects.create(
            gate_pass_number=_number('D7-GP'),
            sale=sale,
            issued_to_name=data['issued_to_name'],
            issued_to_phone=data.get('issued_to_phone', ''),
            vehicle_number=data.get('vehicle_number', ''),
            driver_name=data.get('driver_name', ''),
            notes=data.get('notes', ''),
            issued_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
    else:
        gate_pass.issued_to_name = data['issued_to_name']
        gate_pass.issued_to_phone = data.get('issued_to_phone', '')
        gate_pass.vehicle_number = data.get('vehicle_number', '')
        gate_pass.driver_name = data.get('driver_name', '')
        gate_pass.notes = data.get('notes', '')
        gate_pass.print_status = GatePass.PrintStatus.NOT_PRINTED
        gate_pass.printed_at = None
        gate_pass.updated_by = user
        gate_pass.save(update_fields=[
            'issued_to_name', 'issued_to_phone', 'vehicle_number', 'driver_name',
            'notes', 'print_status', 'printed_at', 'updated_by', 'updated_at',
        ])

    sale_lines = list(AuctionSaleLine.objects.filter(sale=sale).select_related('item'))
    next_line_ids = {line.id for line in sale_lines}
    gate_pass.lines.exclude(sale_line_id__in=next_line_ids).delete()
    existing = set(gate_pass.lines.values_list('sale_line_id', flat=True))
    for sale_line in sale_lines:
        if sale_line.id not in existing:
            GatePassLine.objects.create(
                gate_pass=gate_pass,
                sale_line=sale_line,
                created_by=user,
                updated_by=user,
            )
    return gate_pass


def _validate_sale_lines(lines, *, excluding_sale: AuctionSale | None = None) -> dict:
    if not lines:
        raise ValidationError({'lines': 'At least one sold item is required.'})

    batch_ids = [_batch_id(line) for line in lines]
    if len(set(batch_ids)) != len(batch_ids):
        raise ValidationError({'lines': 'Use one sale line per inventory cost batch and set the quantity there.'})

    batches = {
        str(batch.id): batch
        for batch in InventoryBatch.objects.select_for_update(of=('self',)).select_related('item', 'container', 'container_item', 'container_item__container').filter(id__in=batch_ids).order_by()
    }
    if len(batches) != len(batch_ids):
        raise ValidationError({'lines': 'One or more selected inventory batches do not exist.'})

    for line in lines:
        batch = batches[_batch_id(line)]
        quantity = _quantity(line)
        _line_total(line)
        available_quantity = available_quantity_for_batch(batch, excluding_sale=excluding_sale)
        if quantity > available_quantity:
            raise ValidationError({
                'lines': f'Only {available_quantity} unit(s) are available for {batch.item.part_name} from this cost batch.',
            })
    return batches


@transaction.atomic
def create_auction_sale(
    *,
    user,
    sale_date,
    payment_type,
    customer=None,
    notes='',
    lines=None,
    cheque=None,
    gate_pass=None,
) -> AuctionSale:
    lines = lines or []
    if payment_type != AuctionSale.PaymentType.CASH and customer is None:
        raise ValidationError({'customer': 'Customer is required unless this is a cash sale.'})
    if payment_type == AuctionSale.PaymentType.CHEQUE and not cheque:
        raise ValidationError({'cheque': 'Cheque details are required when payment type is cheque.'})

    batches = _validate_sale_lines(lines)
    total = _sale_total(lines)

    sale = AuctionSale.objects.create(
        sale_number=_number('D7-SALE'),
        sale_date=sale_date,
        payment_type=payment_type,
        customer=customer,
        notes=notes,
        total_amount=total,
        created_by=user,
        updated_by=user,
    )

    for line in lines:
        batch = batches[_batch_id(line)]
        AuctionSaleLine.objects.create(
            sale=sale,
            item=batch.item,
            inventory_batch=batch,
            quantity=_quantity(line),
            sold_price=line['sold_price'],
            raw_unit_cost_snapshot=batch.raw_unit_cost,
            net_unit_cost_snapshot=net_unit_cost_for_batch(batch),
            notes=line.get('notes', ''),
            created_by=user,
            updated_by=user,
        )

    if customer is not None and payment_type != AuctionSale.PaymentType.CASH:
        CustomerLedgerEntry.objects.create(
            customer=customer,
            entry_date=sale_date,
            entry_type=CustomerLedgerEntry.EntryType.SALE,
            description=f'Auction sale {sale.sale_number}',
            debit=total,
            sale=sale,
            created_by=user,
            updated_by=user,
        )

    if payment_type == AuctionSale.PaymentType.CHEQUE:
        pending_status = ChequeStatus.objects.filter(name='Pending', is_active=True).first()
        if pending_status is None:
            raise ValidationError({'cheque': 'Pending cheque status is not configured.'})
        cheque_data = dict(cheque)
        cheque_data['amount'] = total
        create_cheque(
            user=user,
            customer=customer,
            sale=sale,
            status=pending_status,
            **cheque_data,
        )

    _sync_gate_pass_for_sale(user=user, sale=sale, gate_pass_data=gate_pass)

    AuditLog.objects.create(
        actor=user,
        action='auction_sale.created',
        entity_type='AuctionSale',
        entity_id=str(sale.id),
        message=f'Created auction sale {sale.sale_number}',
        metadata={'total_amount': str(total), 'line_count': len(lines)},
    )
    return sale


@transaction.atomic
def update_auction_sale(
    *,
    user,
    sale: AuctionSale,
    sale_date=None,
    customer=None,
    payment_type=None,
    notes=None,
    lines=None,
    gate_pass=None,
) -> AuctionSale:
    sale = (
        AuctionSale.objects
        .select_for_update(of=('self',))
        .select_related('customer')
        .prefetch_related('lines__item', 'ledger_entries', 'cheques__ledger_entries', 'gate_pass__lines')
        .get(id=sale.id)
    )
    if sale.is_cancelled:
        raise ValidationError({'sale': 'Cancelled sales cannot be edited.'})
    if sale.cheques.filter(ledger_entries__entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists():
        raise ValidationError({'sale': 'Sales with settled cheques cannot be edited.'})

    next_payment_type = payment_type or sale.payment_type
    next_customer = customer if customer is not None else sale.customer
    if next_payment_type != AuctionSale.PaymentType.CASH and next_customer is None:
        raise ValidationError({'customer': 'Customer is required unless this is a cash sale.'})

    if sale_date is not None:
        sale.sale_date = sale_date
    if payment_type is not None:
        sale.payment_type = payment_type
    if customer is not None or next_payment_type == AuctionSale.PaymentType.CASH:
        sale.customer = next_customer if next_payment_type != AuctionSale.PaymentType.CASH else None
    if notes is not None:
        sale.notes = notes

    if lines is not None:
        existing_lines = {str(line.id): line for line in sale.lines.select_related('item', 'inventory_batch')}
        desired_existing_ids = {str(line['id']) for line in lines if line.get('id')}
        unknown_ids = desired_existing_ids - set(existing_lines)
        if unknown_ids:
            raise ValidationError({'lines': 'One or more sale lines do not belong to this sale.'})

        normalized = []
        for line in lines:
            if line.get('id'):
                existing = existing_lines[str(line['id'])]
                normalized.append({
                    **line,
                    'inventory_batch': line.get('inventory_batch') or existing.inventory_batch,
                })
            else:
                normalized.append(line)

        batches = _validate_sale_lines(normalized, excluding_sale=sale)

        for removed_id in set(existing_lines) - desired_existing_ids:
            line = existing_lines[removed_id]
            if hasattr(line, 'gate_pass_line'):
                line.gate_pass_line.delete()
            line.delete()

        for line_data in normalized:
            batch = batches[_batch_id(line_data)]
            line_id = line_data.get('id')
            if line_id:
                sale_line = existing_lines[str(line_id)]
            else:
                sale_line = AuctionSaleLine(sale=sale, created_by=user)
            sale_line.item = batch.item
            sale_line.inventory_batch = batch
            sale_line.quantity = _quantity(line_data)
            sale_line.sold_price = line_data['sold_price']
            sale_line.raw_unit_cost_snapshot = batch.raw_unit_cost
            sale_line.net_unit_cost_snapshot = net_unit_cost_for_batch(batch)
            sale_line.notes = line_data.get('notes', sale_line.notes)
            sale_line.updated_by = user
            sale_line.save()

        sale.total_amount = _sale_total(normalized)

    sale.updated_by = user
    sale.save(update_fields=['sale_date', 'payment_type', 'customer', 'notes', 'total_amount', 'updated_by', 'updated_at'])

    sale.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.SALE).delete()
    if sale.customer is not None and sale.payment_type != AuctionSale.PaymentType.CASH:
        CustomerLedgerEntry.objects.create(
            customer=sale.customer,
            entry_date=sale.sale_date,
            entry_type=CustomerLedgerEntry.EntryType.SALE,
            description=f'Auction sale {sale.sale_number}',
            debit=sale.total_amount,
            sale=sale,
            created_by=user,
            updated_by=user,
        )

    if sale.payment_type == AuctionSale.PaymentType.CHEQUE:
        for sale_cheque in sale.cheques.select_related('status'):
            sale_cheque.amount = sale.total_amount
            sale_cheque.customer = sale.customer
            sale_cheque.updated_by = user
            sale_cheque.save(update_fields=['amount', 'customer', 'updated_by', 'updated_at'])

    _sync_gate_pass_for_sale(user=user, sale=sale, gate_pass_data=gate_pass)

    AuditLog.objects.create(
        actor=user,
        action='auction_sale.updated',
        entity_type='AuctionSale',
        entity_id=str(sale.id),
        message=f'Updated auction sale {sale.sale_number}',
        metadata={'total_amount': str(sale.total_amount)},
    )
    return sale


@transaction.atomic
def issue_gate_pass(*, user, sale_line_ids, issued_to_name, issued_to_phone='', vehicle_number='', driver_name='', notes='') -> GatePass:
    if not sale_line_ids:
        raise ValidationError({'sale_line_ids': 'At least one sold item is required.'})
    sale_lines = list(
        AuctionSaleLine.objects.select_for_update(of=('self',))
        .select_related('item', 'sale', 'sale__customer')
        .filter(id__in=sale_line_ids)
    )
    if len(sale_lines) != len(sale_line_ids):
        raise ValidationError({'sale_line_ids': 'One or more sold items do not exist.'})
    sale_ids = {sale_line.sale_id for sale_line in sale_lines}
    if len(sale_ids) != 1:
        raise ValidationError({'sale_line_ids': 'A gate pass must belong to exactly one sale.'})
    sale = sale_lines[0].sale
    gate_pass = _sync_gate_pass_for_sale(
        user=user,
        sale=sale,
        gate_pass_data={
            'issued_to_name': issued_to_name,
            'issued_to_phone': issued_to_phone,
            'vehicle_number': vehicle_number,
            'driver_name': driver_name,
            'notes': notes,
        },
    )
    AuditLog.objects.create(
        actor=user,
        action='gate_pass.issued',
        entity_type='GatePass',
        entity_id=str(gate_pass.id),
        message=f'Issued gate pass {gate_pass.gate_pass_number}',
        metadata={'line_count': len(sale_lines)},
    )
    return gate_pass


@transaction.atomic
def update_gate_pass(*, user, gate_pass: GatePass, sale_line_ids, issued_to_name, issued_to_phone='', vehicle_number='', driver_name='', notes='') -> GatePass:
    gate_pass = GatePass.objects.select_for_update().select_related('sale').get(id=gate_pass.id)
    if gate_pass.status == GatePass.Status.VERIFIED:
        raise ValidationError({'status': 'Verified gate passes cannot be modified.'})
    if gate_pass.sale_id:
        sale = gate_pass.sale
    else:
        sale_lines = list(AuctionSaleLine.objects.select_related('sale').filter(id__in=sale_line_ids))
        sale_ids = {line.sale_id for line in sale_lines}
        if len(sale_ids) != 1:
            raise ValidationError({'sale_line_ids': 'A gate pass must belong to exactly one sale.'})
        sale = sale_lines[0].sale
        gate_pass.sale = sale
        gate_pass.save(update_fields=['sale', 'updated_at'])
    return _sync_gate_pass_for_sale(
        user=user,
        sale=sale,
        gate_pass_data={
            'issued_to_name': issued_to_name,
            'issued_to_phone': issued_to_phone,
            'vehicle_number': vehicle_number,
            'driver_name': driver_name,
            'notes': notes,
        },
    )


@transaction.atomic
def mark_gate_pass_printed(*, user, gate_pass: GatePass) -> GatePass:
    gate_pass = GatePass.objects.select_for_update().get(id=gate_pass.id)
    gate_pass.print_status = GatePass.PrintStatus.PRINTED
    gate_pass.printed_at = timezone.now()
    gate_pass.updated_by = user
    gate_pass.save(update_fields=['print_status', 'printed_at', 'updated_by', 'updated_at'])
    AuditLog.objects.create(
        actor=user,
        action='gate_pass.printed',
        entity_type='GatePass',
        entity_id=str(gate_pass.id),
        message=f'Printed gate pass {gate_pass.gate_pass_number}',
    )
    return gate_pass


@transaction.atomic
def verify_gate_pass(*, user, gate_pass: GatePass) -> GatePass:
    gate_pass = GatePass.objects.select_for_update().get(id=gate_pass.id)
    if gate_pass.status == GatePass.Status.VERIFIED:
        return gate_pass
    if gate_pass.status != GatePass.Status.ISSUED:
        raise ValidationError({'status': 'Only issued gate passes can be verified.'})

    gate_pass.status = GatePass.Status.VERIFIED
    gate_pass.verified_at = timezone.now()
    gate_pass.verified_by = user
    gate_pass.updated_by = user
    gate_pass.save(update_fields=['status', 'verified_at', 'verified_by', 'updated_by', 'updated_at'])

    AuditLog.objects.create(
        actor=user,
        action='gate_pass.verified',
        entity_type='GatePass',
        entity_id=str(gate_pass.id),
        message=f'Verified gate pass {gate_pass.gate_pass_number}',
    )
    return gate_pass
