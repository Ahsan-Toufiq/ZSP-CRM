import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings
from django.db.models import Max, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone

from finance.models import ChequeSettlementAllocation, CustomerLedgerEntry, CustomerPayment, CustomerPaymentAllocation
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


@dataclass(frozen=True)
class CustomerStatement:
    generated_at: timezone.datetime
    customer: Customer
    ledger_rows: list[dict]
    payment_rows: list[dict]
    totals: dict


@dataclass(frozen=True)
class DailyPaymentReport:
    report_date: date
    prepared_at: timezone.datetime
    rows: list[dict]
    totals: dict


def _money(value) -> Decimal:
    return Decimal(value or 0).quantize(Decimal('0.01'))


def _whole_money(value) -> str:
    return f'PKR {_money(value):,.0f}'


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
    payment_allocation_queryset = CustomerPaymentAllocation.objects.select_related('component', 'component__payment')
    opening_queryset = (
        CustomerLedgerEntry.objects
        .filter(
            entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
            description='Opening balance',
            debit__gt=0,
        )
        .prefetch_related(
            Prefetch('cheque_allocations', queryset=ChequeSettlementAllocation.objects.filter(is_reversed=False)),
            'payment_allocations',
        )
    )
    sales_queryset = (
        AuctionSale.objects
        .filter(is_cancelled=False, customer__isnull=False)
        .prefetch_related(
            Prefetch('lines', queryset=line_queryset),
            Prefetch('cheque_allocations', queryset=allocation_queryset),
            Prefetch('payment_allocations', queryset=payment_allocation_queryset),
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
        .prefetch_related(
            Prefetch('auction_sales', queryset=sales_queryset),
            Prefetch('ledger_entries', queryset=opening_queryset, to_attr='opening_receivables'),
        )
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
        for opening in customer.opening_receivables:
            cheque_allocated = sum((_money(allocation.amount) for allocation in opening.cheque_allocations.all()), Decimal('0.00'))
            payment_allocated = sum((_money(allocation.amount) for allocation in opening.payment_allocations.all()), Decimal('0.00'))
            allocated = cheque_allocated + payment_allocated
            outstanding = _money(opening.debit) - allocated
            if outstanding <= 0:
                continue
            days_old = max((today - opening.entry_date).days, 0)
            bucket = _aging_key(days_old)
            aging[bucket] += outstanding
            sale_breakdown.append({
                'sale_number': 'Opening balance',
                'sale_date': opening.entry_date,
                'days_old': days_old,
                'total_amount': _money(opening.debit),
                'settled_amount': allocated,
                'outstanding_amount': outstanding,
                'aging_bucket': bucket,
                'items': [],
                'settlements': [],
            })
        for sale in customer.auction_sales.all():
            cheque_allocated = sum((_money(allocation.amount) for allocation in sale.cheque_allocations.all()), Decimal('0.00'))
            payment_allocated = sum((_money(allocation.amount) for allocation in sale.payment_allocations.all()), Decimal('0.00'))
            allocated = cheque_allocated + payment_allocated
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
                        'reference': allocation.cheque.cheque_number,
                        'method': 'Cheque',
                        'amount': _money(allocation.amount),
                        'created_at': allocation.created_at,
                    }
                    for allocation in sale.cheque_allocations.all()
                ] + [
                    {
                        'cheque_number': '',
                        'reference': allocation.component.payment.payment_number,
                        'method': allocation.component.get_method_display(),
                        'amount': _money(allocation.amount),
                        'created_at': allocation.created_at,
                    }
                    for allocation in sale.payment_allocations.all()
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


def build_customer_statement(*, customer_id) -> CustomerStatement:
    generated_at = timezone.localtime()
    customer = Customer.objects.get(id=customer_id)
    ledger_entries = (
        CustomerLedgerEntry.objects
        .filter(customer=customer)
        .select_related('sale', 'cheque', 'payment')
        .order_by('entry_date', 'created_at')
    )
    running_balance = Decimal('0.00')
    ledger_rows = []
    for entry in ledger_entries:
        running_balance += _money(entry.debit) - _money(entry.credit)
        ledger_rows.append({
            'date': entry.entry_date,
            'type': entry.get_entry_type_display(),
            'description': entry.description,
            'debit': _money(entry.debit),
            'credit': _money(entry.credit),
            'balance': running_balance,
            'reference': (
                entry.sale.sale_number if entry.sale_id else
                entry.cheque.cheque_number if entry.cheque_id else
                entry.payment.payment_number if entry.payment_id else
                '-'
            ),
        })

    payments = (
        customer.payments
        .prefetch_related(
            'components__cheque__status',
            'components__allocations__sale',
            'components__allocations__opening_balance',
            'targets__sale',
            'targets__opening_balance',
        )
        .order_by('payment_date', 'created_at')
    )
    payment_rows = []
    for payment in payments:
        for component in payment.components.all():
            payment_rows.append({
                'date': payment.payment_date,
                'payment_number': payment.payment_number,
                'method': component.get_method_display(),
                'amount': _money(component.amount),
                'reference': component.reference or payment.reference or '-',
                'bank_name': component.bank_name or '-',
                'cheque_number': component.cheque.cheque_number if component.cheque_id else '-',
                'cheque_status': component.cheque.status.name if component.cheque_id else '-',
                'notes': component.notes or payment.notes or '',
                'allocation': ', '.join(
                    f"{target.sale.sale_number if target.sale_id else 'Opening balance'} ({_whole_money(target.amount)})"
                    for target in payment.targets.all()
                ) or payment.get_allocation_mode_display(),
            })

    totals = ledger_entries.aggregate(debit=Sum('debit'), credit=Sum('credit'))
    debit = _money(totals['debit'])
    credit = _money(totals['credit'])
    return CustomerStatement(
        generated_at=generated_at,
        customer=customer,
        ledger_rows=ledger_rows,
        payment_rows=payment_rows,
        totals={
            'debit': debit,
            'credit': credit,
            'balance': debit - credit,
        },
    )


def build_daily_payment_report(*, report_date: date) -> DailyPaymentReport:
    payments = list(
        CustomerPayment.objects
        .filter(payment_date=report_date)
        .select_related('customer')
        .prefetch_related(
            'components__cheque__status',
            'components__allocations__sale',
            'components__allocations__opening_balance',
            'targets__sale',
            'targets__opening_balance',
        )
        .order_by('created_at', 'payment_number')
    )
    customer_ids = {payment.customer_id for payment in payments}
    ledger_by_customer: dict = {}
    for entry in (
        CustomerLedgerEntry.objects
        .filter(customer_id__in=customer_ids)
        .order_by('customer_id', 'entry_date', 'created_at')
    ):
        ledger_by_customer.setdefault(entry.customer_id, []).append(entry)

    rows = []
    method_totals = {
        'cash': Decimal('0.00'),
        'bank_transfer': Decimal('0.00'),
        'cheque': Decimal('0.00'),
        'write_off': Decimal('0.00'),
    }
    total_recorded = Decimal('0.00')
    total_applied = Decimal('0.00')

    for payment in payments:
        entries = ledger_by_customer.get(payment.customer_id, [])
        running = Decimal('0.00')
        balance_before = Decimal('0.00')
        balance_after = None
        for entry in entries:
            if (entry.entry_date, entry.created_at) < (payment.payment_date, payment.created_at):
                running += _money(entry.debit) - _money(entry.credit)
                balance_before = running
                continue
            if entry.payment_id == payment.id:
                running += _money(entry.debit) - _money(entry.credit)
                balance_after = running
                continue
            if entry.entry_date <= payment.payment_date and balance_after is None:
                running += _money(entry.debit) - _money(entry.credit)
        if balance_after is None:
            balance_after = balance_before

        components = []
        payment_applied = Decimal('0.00')
        for component in payment.components.all():
            amount = _money(component.amount)
            method_totals[component.method] += amount
            applied = sum(
                (_money(entry.credit) for entry in entries if entry.payment_id == payment.id and entry.credit > 0),
                Decimal('0.00'),
            ) if component.method != 'cheque' else sum(
                (_money(entry.credit) for entry in entries if entry.cheque_id == component.cheque_id and entry.credit > 0),
                Decimal('0.00'),
            )
            if component.method != 'cheque':
                applied = amount
            payment_applied += applied
            components.append({
                'method': component.get_method_display(),
                'amount': amount,
                'bank_name': component.bank_name,
                'reference': component.reference,
                'cheque_number': component.cheque.cheque_number if component.cheque_id else '',
                'cheque_status': component.cheque.status.name if component.cheque_id else '',
                'applied_amount': applied,
            })

        total_recorded += _money(payment.total_amount)
        total_applied += payment_applied
        rows.append({
            'id': str(payment.id),
            'payment_number': payment.payment_number,
            'customer_id': str(payment.customer_id),
            'customer_name': payment.customer.name,
            'customer_phone': payment.customer.phone,
            'kind': payment.get_kind_display(),
            'allocation_mode': payment.get_allocation_mode_display(),
            'total_amount': _money(payment.total_amount),
            'applied_amount': payment_applied,
            'balance_after': balance_after,
            'notes': payment.notes,
            'components': components,
            'targets': [
                {
                    'label': target.sale.sale_number if target.sale_id else 'Opening balance',
                    'amount': _money(target.amount),
                }
                for target in payment.targets.all()
            ],
        })

    return DailyPaymentReport(
        report_date=report_date,
        prepared_at=timezone.localtime(),
        rows=rows,
        totals={
            'payment_count': len(payments),
            'total_recorded': total_recorded,
            'total_applied': total_applied,
            'cash': method_totals['cash'],
            'bank_transfer': method_totals['bank_transfer'],
            'cheque': method_totals['cheque'],
            'write_off': method_totals['write_off'],
        },
    )


def daily_payment_report_payload(report: DailyPaymentReport) -> dict:
    return {
        'report_date': report.report_date,
        'prepared_at': report.prepared_at,
        'rows': report.rows,
        'totals': report.totals,
    }


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
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=22, bottomMargin=22)
    styles = getSampleStyleSheet()
    detail_style = ParagraphStyle('CreditDetailCell', parent=styles['BodyText'], fontSize=6.8, leading=8.2)
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
        ['Creditors', report.totals['creditor_count'], 'Total Outstanding', _whole_money(report.totals['total_outstanding']), 'Customer Credit', _whole_money(report.totals['customer_credit_balance'])],
    ]
    summary_rows.extend([label, _whole_money(report.totals['aging'][key]), '', '', '', ''] for key, label, *_ in AGING_BUCKETS)
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
            _whole_money(row['remaining_balance']),
            str(row['last_payment_date'] or '-'),
            *[_whole_money(row['aging'][key]) for key, *_ in AGING_BUCKETS],
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
                Paragraph(escape(row['name']), detail_style),
                Paragraph(escape(sale['sale_number']), detail_style),
                Paragraph(sale['sale_date'].strftime('%d %b %Y'), detail_style),
                sale['days_old'],
                _whole_money(sale['total_amount']),
                _whole_money(sale['settled_amount']),
                _whole_money(sale['outstanding_amount']),
                Paragraph('<br/>'.join(f"{item['quantity']} x {escape(item['part_name'])}" for item in sale['items']), detail_style),
            ])
    if len(detail_rows) == 1:
        detail_rows.append(['No outstanding sales', '', '', '', '', '', '', ''])
    detail_table = Table(detail_rows, repeatRows=1, colWidths=[1.45 * inch, 1.2 * inch, 0.95 * inch, 0.45 * inch, 0.95 * inch, 0.95 * inch, 1.05 * inch, 2.05 * inch])
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


def customer_statement_pdf_response(statement: CustomerStatement) -> HttpResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=26, bottomMargin=26)
    styles = getSampleStyleSheet()
    ledger_style = ParagraphStyle('StatementLedgerCell', parent=styles['BodyText'], fontSize=6.5, leading=8)
    story = []
    logo_path = Path(settings.BASE_DIR) / 'static' / 'branding' / 'digi7-logo.png'

    header_data = []
    if logo_path.exists():
        header_data.append(Image(str(logo_path), width=0.62 * inch, height=0.62 * inch))
    else:
        header_data.append(Paragraph('ZSP', styles['Title']))
    header_data.append(Paragraph(f'<b>Customer Statement</b><br/>{escape(statement.customer.name)}', styles['Title']))
    header_data.append(Paragraph(f"Statement date<br/><b>{statement.generated_at.strftime('%Y-%m-%d %H:%M:%S %Z')}</b>", styles['Normal']))
    header = Table([header_data], colWidths=[0.8 * inch, 4.0 * inch, 2.3 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f3faf7')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#0f766e')),
        ('INNERPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([header, Spacer(1, 12)])

    customer_info = Table([
        ['Customer', statement.customer.name, 'Phone', statement.customer.phone],
        ['Status', 'Active' if statement.customer.is_active else 'Inactive', 'Type', statement.customer.get_customer_type_display()],
        ['Address', statement.customer.address or '-', 'Notes', statement.customer.notes or '-'],
    ], colWidths=[0.9 * inch, 2.5 * inch, 0.8 * inch, 2.5 * inch])
    customer_info.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f3faf7')),
        ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#f3faf7')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('INNERPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([customer_info, Spacer(1, 10)])

    summary = Table([[
        'Total debit', _whole_money(statement.totals['debit']),
        'Total credit', _whole_money(statement.totals['credit']),
        'Current balance', _whole_money(statement.totals['balance']),
    ]])
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('INNERPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([summary, Spacer(1, 12)])

    ledger_rows = [['Date', 'Type', 'Description', 'Reference', 'Debit', 'Credit', 'Balance']]
    for row in statement.ledger_rows:
        ledger_rows.append([
            str(row['date']),
            Paragraph(escape(row['type']), ledger_style),
            Paragraph(escape(row['description']), ledger_style),
            Paragraph(escape(str(row['reference'])), ledger_style),
            _whole_money(row['debit']),
            _whole_money(row['credit']),
            _whole_money(row['balance']),
        ])
    if len(ledger_rows) == 1:
        ledger_rows.append(['No financial activity recorded', '', '', '', '', '', ''])
    ledger_table = Table(ledger_rows, repeatRows=1, colWidths=[0.72 * inch, 0.82 * inch, 1.62 * inch, 0.82 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch])
    ledger_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (4, 1), (6, -1), 'RIGHT'),
        ('LEFTPADDING', (4, 1), (6, -1), 4),
        ('RIGHTPADDING', (4, 1), (6, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.extend([Paragraph('<b>Balance Activity</b>', styles['Heading2']), ledger_table, Spacer(1, 12)])

    payment_rows = [['Date', 'Payment', 'Method', 'Amount', 'Applied to', 'Cheque / Ref', 'Status']]
    for row in statement.payment_rows:
        payment_rows.append([
            str(row['date']),
            row['payment_number'],
            row['method'],
            _whole_money(row['amount']),
            Paragraph(escape(row['allocation']), ledger_style),
            row['cheque_number'] if row['cheque_number'] != '-' else row['reference'],
            row['cheque_status'],
        ])
    if len(payment_rows) == 1:
        payment_rows.append(['No direct payments recorded', '', '', '', '', '', ''])
    payment_table = Table(payment_rows, repeatRows=1, colWidths=[0.72 * inch, 1.0 * inch, 0.9 * inch, 0.88 * inch, 1.45 * inch, 1.0 * inch, 0.78 * inch])
    payment_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
    ]))
    story.extend([Paragraph('<b>Payment Details</b>', styles['Heading2']), payment_table])
    story.append(Spacer(1, 12))
    story.append(Paragraph('Positive balance means the customer still owes ZSP. Negative balance means the customer has an advance or credit with ZSP.', styles['BodyText']))
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    safe_name = ''.join(ch if ch.isalnum() else '-' for ch in statement.customer.name.lower()).strip('-') or 'customer'
    response['Content-Disposition'] = f'attachment; filename="zsp-customer-statement-{safe_name}.pdf"'
    return response


def daily_payment_report_pdf_response(report: DailyPaymentReport) -> HttpResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=22, bottomMargin=22)
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle('DailyPaymentCell', parent=styles['BodyText'], fontSize=7, leading=9)
    story = []
    logo_path = Path(settings.BASE_DIR) / 'static' / 'branding' / 'digi7-logo.png'
    logo = Image(str(logo_path), width=0.62 * inch, height=0.62 * inch) if logo_path.exists() else Paragraph('<b>ZSP</b>', styles['Title'])
    header = Table([[
        logo,
        Paragraph('<b>ZSP Daily Payment Report</b><br/><font size="9">Customer receipts and balance activity</font>', styles['Title']),
        Paragraph(
            f'Report date<br/><b>{report.report_date.strftime("%d %B %Y")}</b><br/>'
            f'Prepared {report.prepared_at.strftime("%d %B %Y, %I:%M %p")}',
            styles['Normal'],
        ),
    ]], colWidths=[0.8 * inch, 6.7 * inch, 3.3 * inch])
    header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f3faf7')),
        ('BOX', (0, 0), (-1, -1), 0.8, colors.HexColor('#0f766e')),
        ('INNERPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([header, Spacer(1, 12)])

    summary = Table([[
        'Payments', str(report.totals['payment_count']),
        'Total recorded', _whole_money(report.totals['total_recorded']),
        'Applied to balance', _whole_money(report.totals['total_applied']),
        'Cash', _whole_money(report.totals['cash']),
        'Bank transfer', _whole_money(report.totals['bank_transfer']),
        'Cheque', _whole_money(report.totals['cheque']),
        'Write-off', _whole_money(report.totals['write_off']),
    ]], colWidths=[0.62 * inch, 0.55 * inch, 0.82 * inch, 0.9 * inch, 0.9 * inch, 0.9 * inch, 0.42 * inch, 0.82 * inch, 0.75 * inch, 0.82 * inch, 0.5 * inch, 0.82 * inch, 0.55 * inch, 0.82 * inch])
    summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0f766e')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 6.4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('INNERPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.extend([summary, Spacer(1, 14)])

    rows = [['Payment', 'Customer', 'Method details', 'Allocation', 'Recorded', 'Applied', 'Balance after', 'Notes']]
    for row in report.rows:
        method_lines = []
        for component in row['components']:
            context = component['cheque_number'] or component['reference'] or component['bank_name']
            status = f" ({component['cheque_status']})" if component['cheque_status'] else ''
            method_lines.append(f"{component['method']}: {_whole_money(component['amount'])}{status}{' - ' + context if context else ''}")
        allocation = '<br/>'.join(
            f"{target['label']}: {_whole_money(target['amount'])}" for target in row['targets']
        ) or row['allocation_mode']
        rows.append([
            Paragraph(escape(row['payment_number']), cell_style),
            Paragraph(f"<b>{escape(row['customer_name'])}</b><br/>{escape(row['customer_phone'])}", cell_style),
            Paragraph('<br/>'.join(escape(line) for line in method_lines), cell_style),
            Paragraph('<br/>'.join(escape(line) for line in allocation.split('<br/>')), cell_style),
            _whole_money(row['total_amount']),
            _whole_money(row['applied_amount']),
            _whole_money(row['balance_after']),
            Paragraph(escape(row['notes'] or '-'), cell_style),
        ])
    if len(rows) == 1:
        rows.append(['No payments recorded for this date', '', '', '', '', '', '', ''])
    table = Table(rows, repeatRows=1, colWidths=[1.05 * inch, 1.45 * inch, 2.2 * inch, 1.55 * inch, 0.95 * inch, 0.95 * inch, 1.05 * inch, 1.4 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#111827')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (4, 1), (6, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('INNERPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    doc.build(story)

    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="zsp-daily-payments-{report.report_date.isoformat()}.pdf"'
    return response
