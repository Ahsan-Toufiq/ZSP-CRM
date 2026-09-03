from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from finance.models import Cheque, ChequeStatus, CustomerLedgerEntry
from finance.services import create_cheque
from operations.models import AuctionSale, AuctionSaleLine, ContainerItem, GatePass, GatePassLine


def _number(prefix: str) -> str:
    now = timezone.localtime()
    return f'{prefix}-{now:%Y%m%d-%H%M%S}-{str(timezone.now().timestamp()).replace(".", "")[-5:]}'


def _sale_total(lines) -> Decimal:
    return sum((Decimal(str(line['sold_price'])) for line in lines), Decimal('0.00'))


@transaction.atomic
def create_auction_sale(*, user, sale_date, payment_type, customer=None, notes='', lines=None, cheque=None) -> AuctionSale:
    lines = lines or []
    if not lines:
        raise ValidationError({'lines': 'At least one sold item is required.'})
    if payment_type != AuctionSale.PaymentType.CASH and customer is None:
        raise ValidationError({'customer': 'Customer is required unless this is a cash sale.'})
    if payment_type == AuctionSale.PaymentType.CHEQUE and not cheque:
        raise ValidationError({'cheque': 'Cheque details are required when payment type is cheque.'})

    item_ids = [line['item'].id if hasattr(line['item'], 'id') else line['item'] for line in lines]
    if len(set(item_ids)) != len(item_ids):
        raise ValidationError({'lines': 'The same item cannot be sold twice in one sale.'})

    items = {
        item.id: item
        for item in ContainerItem.objects.select_for_update().filter(id__in=item_ids)
    }
    if len(items) != len(item_ids):
        raise ValidationError({'lines': 'One or more selected items do not exist.'})

    for line in lines:
        item_id = line['item'].id if hasattr(line['item'], 'id') else line['item']
        item = items[item_id]
        if item.status != ContainerItem.Status.AVAILABLE:
            raise ValidationError({'lines': f'Item {item.lot_number} is not available for sale.'})
        price = Decimal(str(line['sold_price']))
        if price <= 0:
            raise ValidationError({'lines': 'Sold price must be greater than zero.'})
    total = _sale_total(lines)
    if payment_type == AuctionSale.PaymentType.CHEQUE and Decimal(str(cheque['amount'])) != total:
        raise ValidationError({'cheque': 'Cheque amount must match the sale total for cheque payments.'})

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
        item_id = line['item'].id if hasattr(line['item'], 'id') else line['item']
        item = items[item_id]
        AuctionSaleLine.objects.create(
            sale=sale,
            item=item,
            sold_price=line['sold_price'],
            notes=line.get('notes', ''),
            created_by=user,
            updated_by=user,
        )
        item.status = ContainerItem.Status.SOLD
        item.updated_by = user
        item.save(update_fields=['status', 'updated_by', 'updated_at'])

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
        create_cheque(
            user=user,
            customer=customer,
            sale=sale,
            status=pending_status,
            **cheque,
        )

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
def update_auction_sale(*, user, sale: AuctionSale, sale_date=None, customer=None, payment_type=None, notes=None, lines=None) -> AuctionSale:
    sale = (
        AuctionSale.objects
        .select_for_update()
        .select_related('customer')
        .prefetch_related('lines__gate_pass_line', 'lines__item', 'ledger_entries', 'cheques__ledger_entries')
        .get(id=sale.id)
    )
    if sale.is_cancelled:
        raise ValidationError({'sale': 'Cancelled sales cannot be edited.'})
    if any(hasattr(line, 'gate_pass_line') for line in sale.lines.all()):
        raise ValidationError({'sale': 'Sales already attached to a gate pass cannot be edited. Edit the gate pass first or create an adjustment.'})
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
        existing_lines = {str(line.id): line for line in sale.lines.select_related('item')}
        if set(existing_lines) != {str(line['id']) for line in lines}:
            raise ValidationError({'lines': 'Editing sale items is not supported here. Create a corrected sale if items were wrong.'})
        total = Decimal('0.00')
        for line_data in lines:
            line = existing_lines[str(line_data['id'])]
            price = Decimal(str(line_data['sold_price']))
            if price <= 0:
                raise ValidationError({'lines': 'Sold price must be greater than zero.'})
            line.sold_price = price
            line.notes = line_data.get('notes', line.notes)
            line.updated_by = user
            line.save(update_fields=['sold_price', 'notes', 'updated_by', 'updated_at'])
            total += price
        sale.total_amount = total

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
    if len(set(sale_line_ids)) != len(sale_line_ids):
        raise ValidationError({'sale_line_ids': 'Duplicate sold items are not allowed.'})

    sale_lines = list(
        AuctionSaleLine.objects.select_for_update()
        .select_related('item', 'sale')
        .filter(id__in=sale_line_ids)
    )
    if len(sale_lines) != len(sale_line_ids):
        raise ValidationError({'sale_line_ids': 'One or more sold items do not exist.'})
    if GatePassLine.objects.filter(sale_line_id__in=sale_line_ids).exists():
        raise ValidationError({'sale_line_ids': 'One or more sold items already have a gate pass.'})

    for sale_line in sale_lines:
        if sale_line.sale.is_cancelled:
            raise ValidationError({'sale_line_ids': 'Cannot issue gate pass for a cancelled sale.'})
        if sale_line.item.status != ContainerItem.Status.SOLD:
            raise ValidationError({'sale_line_ids': f'Item {sale_line.item.lot_number} is not ready for gate pass.'})

    gate_pass = GatePass.objects.create(
        gate_pass_number=_number('D7-GP'),
        issued_to_name=issued_to_name,
        issued_to_phone=issued_to_phone,
        vehicle_number=vehicle_number,
        driver_name=driver_name,
        notes=notes,
        issued_at=timezone.now(),
        created_by=user,
        updated_by=user,
    )

    for sale_line in sale_lines:
        GatePassLine.objects.create(
            gate_pass=gate_pass,
            sale_line=sale_line,
            created_by=user,
            updated_by=user,
        )
        item = sale_line.item
        item.status = ContainerItem.Status.GATE_PASS_ISSUED
        item.updated_by = user
        item.save(update_fields=['status', 'updated_by', 'updated_at'])

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
    gate_pass = GatePass.objects.select_for_update().get(id=gate_pass.id)
    if gate_pass.status == GatePass.Status.VERIFIED:
        raise ValidationError({'status': 'Verified gate passes cannot be modified.'})
    if not sale_line_ids:
        raise ValidationError({'sale_line_ids': 'At least one sold item is required.'})
    if len(set(sale_line_ids)) != len(sale_line_ids):
        raise ValidationError({'sale_line_ids': 'Duplicate sold items are not allowed.'})

    sale_lines = list(
        AuctionSaleLine.objects.select_for_update()
        .select_related('item', 'sale')
        .filter(id__in=sale_line_ids)
    )
    if len(sale_lines) != len(sale_line_ids):
        raise ValidationError({'sale_line_ids': 'One or more sold items do not exist.'})

    current_lines = list(gate_pass.lines.select_related('sale_line__item'))
    current_ids = {line.sale_line_id for line in current_lines}
    next_ids = {line.id for line in sale_lines}
    removed = [line for line in current_lines if line.sale_line_id not in next_ids]
    added = [line for line in sale_lines if line.id not in current_ids]

    if GatePassLine.objects.filter(sale_line_id__in=[line.id for line in added]).exclude(gate_pass=gate_pass).exists():
        raise ValidationError({'sale_line_ids': 'One or more sold items already have another gate pass.'})

    for sale_line in added:
        if sale_line.sale.is_cancelled or sale_line.item.status != ContainerItem.Status.SOLD:
            raise ValidationError({'sale_line_ids': f'Item {sale_line.item.lot_number} is not ready for gate pass.'})

    for line in removed:
        item = line.sale_line.item
        item.status = ContainerItem.Status.SOLD
        item.updated_by = user
        item.save(update_fields=['status', 'updated_by', 'updated_at'])
        line.delete()

    for sale_line in added:
        GatePassLine.objects.create(gate_pass=gate_pass, sale_line=sale_line, created_by=user, updated_by=user)
        item = sale_line.item
        item.status = ContainerItem.Status.GATE_PASS_ISSUED
        item.updated_by = user
        item.save(update_fields=['status', 'updated_by', 'updated_at'])

    gate_pass.issued_to_name = issued_to_name
    gate_pass.issued_to_phone = issued_to_phone
    gate_pass.vehicle_number = vehicle_number
    gate_pass.driver_name = driver_name
    gate_pass.notes = notes
    gate_pass.print_status = GatePass.PrintStatus.NOT_PRINTED
    gate_pass.printed_at = None
    gate_pass.updated_by = user
    gate_pass.save(update_fields=[
        'issued_to_name', 'issued_to_phone', 'vehicle_number', 'driver_name',
        'notes', 'print_status', 'printed_at', 'updated_by', 'updated_at',
    ])

    AuditLog.objects.create(
        actor=user,
        action='gate_pass.updated',
        entity_type='GatePass',
        entity_id=str(gate_pass.id),
        message=f'Updated gate pass {gate_pass.gate_pass_number}',
        metadata={'line_count': len(next_ids)},
    )
    return gate_pass


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

    for line in gate_pass.lines.select_related('sale_line__item'):
        item = line.sale_line.item
        item.status = ContainerItem.Status.RELEASED
        item.updated_by = user
        item.save(update_fields=['status', 'updated_by', 'updated_at'])

    AuditLog.objects.create(
        actor=user,
        action='gate_pass.verified',
        entity_type='GatePass',
        entity_id=str(gate_pass.id),
        message=f'Verified gate pass {gate_pass.gate_pass_number}',
    )
    return gate_pass
