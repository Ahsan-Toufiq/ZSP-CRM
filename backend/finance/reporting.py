import csv
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

from django.conf import settings
from django.db.models import Max, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone

from finance.models import ChequeSettlementAllocation, CustomerLedgerEntry
from operations.models import AuctionSale, AuctionSaleLine, Customer


AGING_BUCKETS = (
    ('current', '0-30 days', 0, 30),
    ('days_31_60', '31-60 days', 31, 60),
    ('days_61_90', '61-90 days', 61, 90),
    ('over_90', '90+ days', 91, None),
)


@dataclass(frozen=True)
class CreditReport:
    generated_at: timezone.datetime
    customers: list[dict]
    totals: dict


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal('0.01'))


def _aging_key(days_old: int) -> str:
    for key, _label, start, end in AGING_BUCKETS:
        if days_old >= start and (end is None or days_old <= end):
            return key
    return 'current'


def build_credit_report() -> CreditReport:
    today = timezone.localdate()
    generated_at = timezone.localtime()
    line_queryset = AuctionSaleLine.objects.select_related('item')
    allocation_queryset = ChequeSettlementAllocation.objects.select_related('cheque').filter(is_reversed=False)
    sales_queryset = (
        AuctionSale.objects
        .filter(is_cancelled=False, customer__isnull=False)
        .prefetch_related(
            Prefetch('lines', queryset=line_queryset),
            Prefetch('cheque_allocations', queryset=allocation_queryset),
        )
        .order_by('sale_date', 'created_at')
    )
    customers = (
        Customer.objects
        .annotate(
            total_debit=Coalesce(Sum('ledger_entries__debit'), Value(Decimal('0.00'))),
            total_credit=Coalesce(Sum('ledger_entries__credit'), Value(Decimal('0.00'))),
            last_payment_date=Max('ledger_entries__entry_date', filter=Q(ledger_entries__credit__gt=0)),
        )
        .prefetch_related(Prefetch('auction_sales', queryset=sales_queryset))
        .order_by('name')
    )

    report_rows = []
    total_aging = {key: Decimal('0.00') for key, *_ in AGING_BUCKETS}
    total_outstanding = Decimal('0.00')
    total_credit_balance = Decimal('0.00')

    for customer in customers:
        balance = _money(customer.total_debit) - _money(customer.total_credit)
        aging = {key: Decimal('0.00') for key, *_ in AGING_BUCKETS}
        sale_breakdown = []
        for sale in customer.auction_sales.all():
            allocated = sum((_money(allocation.amount) for allocation in sale.cheque_allocations.all()), Decimal('0.00'))
            outstanding = _money(sale.receivable_amount) - allocated
            if outstanding <= 0:
                continue
            days_old = max((today - sale.sale_date).days, 0)
            bucket = _aging_key(days_old)
            aging[bucket] += outstanding
            sale_breakdown.append({
                'sale_number': sale.sale_number,
                'sale_date': sale.sale_date,
                'days_old': days_old,
                'total_amount': _money(sale.total_amount),
                'settled_amount': allocated,
                'outstanding_amount': outstanding,
                'aging_bucket': bucket,
                'items': [
                    {
                        'part_name': line.item.part_name,
                        'part_number': line.item.part_number,
                        'category': line.item.category,
                        'quantity': line.quantity,
                        'sold_price': _money(line.sold_price),
                        'line_total': _money(line.quantity * line.sold_price),
                    }
                    for line in sale.lines.all()
                ],
                'settlements': [
                    {
                        'cheque_number': allocation.cheque.cheque_number,
                        'amount': _money(allocation.amount),
                        'created_at': allocation.created_at,
                    }
                    for allocation in sale.cheque_allocations.all()
                ],
            })

        positive_balance = max(balance, Decimal('0.00'))
        for key in aging:
            total_aging[key] += aging[key]
        total_outstanding += positive_balance
        if balance < 0:
            total_credit_balance += abs(balance)

        report_rows.append({
            'id': str(customer.id),
            'name': customer.name,
            'phone': customer.phone,
            'is_active': customer.is_active,
            'total_debit': _money(customer.total_debit),
            'total_credit': _money(customer.total_credit),
            'remaining_balance': balance,
            'last_payment_date': customer.last_payment_date,
            'aging': aging,
            'sale_breakdown': sale_breakdown,
        })

    report_rows.sort(key=lambda row: (row['remaining_balance'] <= 0, -row['remaining_balance'], row['name'].lower()))
    return CreditReport(
        generated_at=generated_at,
        customers=report_rows,
        totals={
            'creditor_count': sum(1 for row in report_rows if row['remaining_balance'] > 0),
            'customer_count': len(report_rows),
            'total_outstanding': total_outstanding,
            'customer_credit_balance': total_credit_balance,
            'aging': total_aging,
        },
    )


def credit_report_payload(report: CreditReport) -> dict:
    return {
        'generated_at': report.generated_at.isoformat(),
        'aging_buckets': [{'key': key, 'label': label} for key, label, *_ in AGING_BUCKETS],
        'totals': report.totals,
        'customers': report.customers,
    }


def credit_report_csv_response(report: CreditReport) -> HttpResponse:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['ZSP Credit, Aging, And Customer Balance Report'])
    writer.writerow(['Generated at', report.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')])
    writer.writerow([])
    writer.writerow(['Summary'])
    writer.writerow(['Creditors', report.totals['creditor_count']])
    writer.writerow(['Total outstanding', report.totals['total_outstanding']])
    writer.writerow(['Customer credit balance', report.totals['customer_credit_balance']])
    for key, label, *_ in AGING_BUCKETS:
        writer.writerow([label, report.totals['aging'][key]])
    writer.writerow([])
    writer.writerow(['Customer', 'Contact Number', 'Remaining Balance', 'Last Payment Date', *[label for _key, label, *_ in AGING_BUCKETS]])
    for row in report.customers:
        writer.writerow([
            row['name'],
            row['phone'],
            row['remaining_balance'],
            row['last_payment_date'] or '',
            *[row['aging'][key] for key, *_ in AGING_BUCKETS],
        ])
    writer.writerow([])
    writer.writerow(['Per Customer Sale Breakdown'])
    writer.writerow(['Customer', 'Sale Number', 'Sale Date', 'Days Old', 'Sale Total', 'Settled', 'Outstanding', 'Aging Bucket', 'Items'])
    for row in report.customers:
        for sale in row['sale_breakdown']:
            writer.writerow([
                row['name'],
                sale['sale_number'],
                sale['sale_date'],
                sale['days_old'],
                sale['total_amount'],
                sale['settled_amount'],
                sale['outstanding_amount'],
                sale['aging_bucket'],
                '; '.join(f"{item['quantity']} x {item['part_name']}" for item in sale['items']),
            ])

    response = HttpResponse(buffer.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="zsp-credit-aging-report.csv"'
    return response


def credit_report_pdf_response(report: CreditReport) -> HttpResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=22, bottomMargin=22)
    styles = getSampleStyleSheet()
    story = []
    logo_path = Path(settings.BASE_DIR) / 'static' / 'branding' / 'digi7-logo.png'

    header_data = []
    if logo_path.exists():
        header_data.append(Image(str(logo_path), width=0.62 * inch, height=0.62 * inch))
    else:
        header_data.append(Paragraph('ZSP', styles['Title']))
    header_data.append(Paragraph('<b>ZSP Credit, Aging, And Customer Balance Report</b><br/>Generated by Digi7', styles['Title']))
    header_data.append(Paragraph(f"Generated at<br/><b>{report.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}</b>", styles['Normal']))
    header = Table([header_data], colWidths=[0.8 * inch, 6.6 * inch, 3.2 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f3faf7')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#0f766e')),
        ('INNERPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([header, Spacer(1, 12)])

    summary_rows = [
        ['Creditors', report.totals['creditor_count'], 'Total Outstanding', f"PKR {report.totals['total_outstanding']:,.2f}", 'Customer Credit', f"PKR {report.totals['customer_credit_balance']:,.2f}"],
    ]
    summary_rows.extend([label, f"PKR {report.totals['aging'][key]:,.2f}", '', '', '', ''] for key, label, *_ in AGING_BUCKETS)
    summary = Table(summary_rows, repeatRows=0)
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d9e7e2')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fbf9')]),
    ]))
    story.extend([Paragraph('<b>Summary</b>', styles['Heading2']), summary, Spacer(1, 12)])

    customer_rows = [['Customer', 'Contact', 'Balance', 'Last Payment', *[label for _key, label, *_ in AGING_BUCKETS]]]
    for row in report.customers:
        customer_rows.append([
            row['name'],
            row['phone'],
            f"PKR {row['remaining_balance']:,.2f}",
            str(row['last_payment_date'] or '-'),
            *[f"PKR {row['aging'][key]:,.2f}" for key, *_ in AGING_BUCKETS],
        ])
    customer_table = Table(customer_rows, repeatRows=1, colWidths=[1.65 * inch, 1.25 * inch, 1.1 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch])
    customer_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7.2),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.extend([Paragraph('<b>Total Credit Report And Aging</b>', styles['Heading2']), customer_table, Spacer(1, 12)])

    detail_rows = [['Customer', 'Sale', 'Date', 'Days', 'Total', 'Settled', 'Outstanding', 'Items']]
    for row in report.customers:
        for sale in row['sale_breakdown']:
            detail_rows.append([
                row['name'],
                sale['sale_number'],
                str(sale['sale_date']),
                sale['days_old'],
                f"PKR {sale['total_amount']:,.2f}",
                f"PKR {sale['settled_amount']:,.2f}",
                f"PKR {sale['outstanding_amount']:,.2f}",
                Paragraph('<br/>'.join(f"{item['quantity']} x {item['part_name']}" for item in sale['items']), styles['BodyText']),
            ])
    if len(detail_rows) == 1:
        detail_rows.append(['No outstanding sales', '', '', '', '', '', '', ''])
    detail_table = Table(detail_rows, repeatRows=1, colWidths=[1.45 * inch, 1.25 * inch, 0.82 * inch, 0.45 * inch, 0.95 * inch, 0.95 * inch, 1.05 * inch, 2.05 * inch])
    detail_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.extend([Paragraph('<b>Per Customer Credit Balance Breakdown</b>', styles['Heading2']), detail_table])
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="zsp-credit-aging-report.pdf"'
    return response
