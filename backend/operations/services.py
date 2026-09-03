from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from finance.models import CustomerLedgerEntry
from operations.models import AuctionSale, AuctionSaleLine, ContainerItem, GatePass, GatePassLine


def _number(prefix: str) -> str:
    now = timezone.localtime()
    return f'{prefix}-{now:%Y%m%d-%H%M%S}-{str(timezone.now().timestamp()).replace(".", "")[-5:]}'


@transaction.atomic
def create_auction_sale(*, user, sale_date, payment_type, customer=None, notes='', lines=None) -> AuctionSale:
    lines = lines or []
    if not lines:
        raise ValidationError({'lines': 'At least one sold item is required.'})
    if payment_type != AuctionSale.PaymentType.CASH and customer is None:
        raise ValidationError({'customer': 'Customer is required unless this is a cash sale.'})

    item_ids = [line['item'].id if hasattr(line['item'], 'id') else line['item'] for line in lines]
    if len(set(item_ids)) != len(item_ids):
        raise ValidationError({'lines': 'The same item cannot be sold twice in one sale.'})

    items = {
        item.id: item
        for item in ContainerItem.objects.select_for_update().filter(id__in=item_ids)
    }
    if len(items) != len(item_ids):
        raise ValidationError({'lines': 'One or more selected items do not exist.'})

    total = Decimal('0.00')
    for line in lines:
        item_id = line['item'].id if hasattr(line['item'], 'id') else line['item']
        item = items[item_id]
        if item.status != ContainerItem.Status.AVAILABLE:
            raise ValidationError({'lines': f'Item {item.lot_number} is not available for sale.'})
        price = Decimal(str(line['sold_price']))
        if price <= 0:
            raise ValidationError({'lines': 'Sold price must be greater than zero.'})
        total += price

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
