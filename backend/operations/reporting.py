import csv
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

from django.conf import settings
from django.db.models import IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone

from operations.models import AuctionSale, InventoryBatch


@dataclass(frozen=True)
class InventoryReport:
    generated_at: timezone.datetime
    scope_label: str
    rows: list[dict]
    totals: dict


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal('0.01'))


def _logo_path() -> Path:
    return Path(settings.BASE_DIR) / 'static' / 'branding' / 'digi7-logo.png'


def _content_disposition(filename: str, *, inline: bool = False) -> str:
    disposition = 'inline' if inline else 'attachment'
    return f'{disposition}; filename="{filename}"'


def _report_header(story, styles, title: str, subtitle: str, generated_at, *, generated_label='Generated at'):
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle

    logo_path = _logo_path()
    header_data = []
    if logo_path.exists():
        header_data.append(Image(str(logo_path), width=0.62 * inch, height=0.62 * inch))
    else:
        header_data.append(Paragraph('<b>ZSP</b>', styles['Title']))
    header_data.append(Paragraph(f'<b>{title}</b><br/><font size="9">{subtitle}</font>', styles['Title']))
    header_data.append(Paragraph(f'{generated_label}<br/><b>{generated_at.strftime("%Y-%m-%d %H:%M:%S %Z")}</b>', styles['Normal']))
    header = Table([header_data], colWidths=[0.8 * inch, 6.7 * inch, 3.3 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f3faf7')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#0f766e')),
        ('INNERPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([header, Spacer(1, 12)])


def build_inventory_report(*, container_id=None) -> InventoryReport:
    generated_at = timezone.localtime()
    queryset = (
        InventoryBatch.objects
        .select_related('item', 'container', 'container_item')
        .annotate(
            sold_quantity_total=Coalesce(
                Sum('sale_lines__quantity', filter=Q(sale_lines__sale__is_cancelled=False)),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by('container__reference', 'item__part_name', 'item__part_number', 'item__category', 'created_at')
    )
    if container_id:
        queryset = queryset.filter(container_id=container_id)

    rows = []
    for batch in queryset:
        available = max(int(batch.quantity) - int(batch.sold_quantity_total or 0), 0)
        if available <= 0:
            continue
        raw_total = _money(batch.raw_unit_cost) * Decimal(available)
        net_total = _money(batch.net_unit_cost) * Decimal(available)
        rows.append({
            'part_name': batch.item.part_name,
            'part_number': batch.item.part_number or '',
            'category': batch.item.category or '',
            'unit': batch.item.unit or 'piece',
            'container_reference': batch.container.reference if batch.container_id else batch.source_label or 'Manual',
            'container_status': batch.container.get_status_display() if batch.container_id else '',
            'source_label': batch.source_label or '',
            'batch_quantity': batch.quantity,
            'sold_quantity': batch.sold_quantity_total or 0,
            'available_quantity': available,
            'raw_unit_cost': _money(batch.raw_unit_cost),
            'net_unit_cost': _money(batch.net_unit_cost),
            'added_cost_share_unit': _money(batch.net_unit_cost) - _money(batch.raw_unit_cost),
            'raw_total': raw_total,
            'net_total': net_total,
            'added_cost_share_total': net_total - raw_total,
            'notes': batch.notes or '',
        })

    scope_label = 'All available inventory'
    if container_id and rows:
        scope_label = f"Available inventory for {rows[0]['container_reference']}"
    elif container_id:
        scope_label = 'Available inventory for selected container'

    return InventoryReport(
        generated_at=generated_at,
        scope_label=scope_label,
        rows=rows,
        totals={
            'row_count': len(rows),
            'available_quantity': sum(row['available_quantity'] for row in rows),
            'raw_total': sum((row['raw_total'] for row in rows), Decimal('0.00')),
            'net_total': sum((row['net_total'] for row in rows), Decimal('0.00')),
            'added_cost_share_total': sum((row['added_cost_share_total'] for row in rows), Decimal('0.00')),
        },
    )


def inventory_report_csv_response(report: InventoryReport) -> HttpResponse:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['ZSP Available Inventory Report'])
    writer.writerow(['Scope', report.scope_label])
    writer.writerow(['Generated at', report.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')])
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Rows', report.totals['row_count']])
    writer.writerow(['Available quantity', report.totals['available_quantity']])
    writer.writerow(['Raw total', report.totals['raw_total']])
    writer.writerow(['Added cost share', report.totals['added_cost_share_total']])
    writer.writerow(['Net total', report.totals['net_total']])
    writer.writerow([])
    writer.writerow([
        'Part name', 'Part number', 'Category', 'Unit', 'Source container', 'Container status',
        'Batch quantity', 'Sold quantity', 'Available quantity', 'Raw unit cost', 'Added share / unit',
        'Net unit cost', 'Raw total', 'Added share total', 'Net total', 'Notes',
    ])
    for row in report.rows:
        writer.writerow([
            row['part_name'], row['part_number'], row['category'], row['unit'],
            row['container_reference'], row['container_status'], row['batch_quantity'],
            row['sold_quantity'], row['available_quantity'], row['raw_unit_cost'],
            row['added_cost_share_unit'], row['net_unit_cost'], row['raw_total'],
            row['added_cost_share_total'], row['net_total'], row['notes'],
        ])

    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = _content_disposition('zsp-available-inventory.csv')
    return response


def inventory_report_pdf_response(report: InventoryReport) -> HttpResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=18, bottomMargin=18)
    styles = getSampleStyleSheet()
    story = []
    _report_header(story, styles, 'ZSP Available Inventory Report', report.scope_label, report.generated_at)

    summary = Table([[
        'Rows', report.totals['row_count'],
        'Available Qty', report.totals['available_quantity'],
        'Raw Total', f"PKR {report.totals['raw_total']:,.2f}",
        'Net Total', f"PKR {report.totals['net_total']:,.2f}",
    ]])
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('INNERPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([summary, Spacer(1, 10)])

    rows = [[
        'Part', 'No.', 'Category', 'Source', 'Avail', 'Raw Unit', 'Add/Unit',
        'Net Unit', 'Raw Total', 'Add Total', 'Net Total',
    ]]
    for row in report.rows:
        rows.append([
            Paragraph(row['part_name'], styles['BodyText']),
            Paragraph(row['part_number'] or '-', styles['BodyText']),
            Paragraph(row['category'] or '-', styles['BodyText']),
            Paragraph(row['container_reference'], styles['BodyText']),
            f"{row['available_quantity']} {row['unit']}",
            f"PKR {row['raw_unit_cost']:,.2f}",
            f"PKR {row['added_cost_share_unit']:,.2f}",
            f"PKR {row['net_unit_cost']:,.2f}",
            f"PKR {row['raw_total']:,.2f}",
            f"PKR {row['added_cost_share_total']:,.2f}",
            f"PKR {row['net_total']:,.2f}",
        ])
    if len(rows) == 1:
        rows.append(['No available inventory', '', '', '', '', '', '', '', '', '', ''])

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[1.55 * inch, 0.85 * inch, 0.95 * inch, 1.05 * inch, 0.58 * inch, 0.82 * inch, 0.82 * inch, 0.82 * inch, 0.9 * inch, 0.9 * inch, 0.95 * inch],
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.5),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.append(table)
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = _content_disposition('zsp-available-inventory.pdf')
    return response


def sale_invoice_pdf_response(sale: AuctionSale, *, inline: bool = False) -> HttpResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    sale = (
        AuctionSale.objects
        .select_related('customer', 'gate_pass')
        .prefetch_related('lines__item', 'lines__inventory_batch__container', 'cheques')
        .get(id=sale.id)
    )
    generated_at = timezone.localtime()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=26, bottomMargin=26)
    styles = getSampleStyleSheet()
    story = []
    _report_header(story, styles, 'ZSP Sales Invoice', f'Invoice {sale.sale_number}', generated_at, generated_label='Date / time')

    customer_name = sale.customer.name if sale.customer_id else 'Cash customer'
    customer_phone = sale.customer.phone if sale.customer_id else '-'
    try:
        gate_pass_number = sale.gate_pass.gate_pass_number
    except AuctionSale.gate_pass.RelatedObjectDoesNotExist:
        gate_pass_number = '-'
    invoice_meta = Table([
        ['Invoice #', sale.sale_number, 'Date', str(sale.sale_date)],
        ['Customer', customer_name, 'Contact', customer_phone],
        ['Payment', sale.get_payment_type_display(), 'Gate pass', gate_pass_number],
    ], colWidths=[1.2 * inch, 2.4 * inch, 1.2 * inch, 2.1 * inch])
    invoice_meta.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3faf7')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f3faf7')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('INNERPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([invoice_meta, Spacer(1, 14)])

    item_rows = [['Item', 'Part No.', 'Category', 'Quantity', 'Unit Price', 'Amount']]
    for line in sale.lines.all():
        item_rows.append([
            Paragraph(line.item.part_name, styles['BodyText']),
            Paragraph(line.item.part_number or '-', styles['BodyText']),
            Paragraph(line.item.category or '-', styles['BodyText']),
            f'{line.quantity} {line.item.unit}',
            f'PKR {line.sold_price:,.2f}',
            f'PKR {(line.quantity * line.sold_price):,.2f}',
        ])
    items = Table(item_rows, repeatRows=1, colWidths=[2.0 * inch, 1.0 * inch, 1.05 * inch, 0.9 * inch, 1.0 * inch, 1.1 * inch])
    items.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.extend([items, Spacer(1, 12)])

    cheque_total = sum((cheque.amount for cheque in sale.cheques.all()), Decimal('0.00'))
    totals = Table([
        ['Items total', f'PKR {sale.total_amount:,.2f}'],
        ['Cash paid', f'PKR {sale.cash_amount:,.2f}'],
        ['Cheque paid', f'PKR {cheque_total:,.2f}'],
        ['Credit amount', f'PKR {sale.credit_amount:,.2f}'],
        ['Balance due', f'PKR {sale.receivable_amount:,.2f}'],
        ['Invoice amount', f'PKR {sale.total_amount:,.2f}'],
    ], colWidths=[2.0 * inch, 1.4 * inch], hAlign='RIGHT')
    totals.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3faf7')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('INNERPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([totals, Spacer(1, 18)])
    story.append(Paragraph('Thank you for your business. This invoice was generated by ZSP through Digi7.', styles['BodyText']))
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = _content_disposition(f'zsp-invoice-{sale.sale_number}.pdf', inline=inline)
    return response
