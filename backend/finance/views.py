from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Avg, Count, DecimalField, F, Max, Min, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth, TruncWeek, TruncYear
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from accounts.permissions import DashboardPermission, FinancePermission, has_tab_access
from finance.models import (
    Cheque,
    ChequeSettlementAllocation,
    ChequeStatus,
    Currency,
    CurrencyCreditor,
    CurrencyCreditorRepayment,
    CurrencyOpeningBalance,
    CurrencyPurchase,
    CurrencySpending,
    Expense,
    CustomerLedgerEntry,
    CustomerPayment,
    CustomerPaymentAllocation,
)
from finance.reporting import (
    build_credit_report,
    build_customer_statement,
    build_daily_payment_report,
    credit_report_csv_response,
    credit_report_payload,
    credit_report_pdf_response,
    customer_statement_pdf_response,
    currency_creditor_statement_pdf_response,
    daily_payment_report_payload,
    daily_payment_report_pdf_response,
)
from finance.services import customer_receivables, delete_currency_acquisition, delete_currency_purchase
from finance.serializers import (
    ChequeSerializer,
    ChequeStatusChangeSerializer,
    ChequeStatusHistorySerializer,
    ChequeStatusSerializer,
    CurrencyPurchaseSerializer,
    CurrencyCreditorSerializer,
    CurrencyCreditorRepaymentSerializer,
    CurrencySerializer,
    CurrencyOpeningBalanceSerializer,
    CurrencySpendingSerializer,
    ExpenseSerializer,
    CustomerBalanceSerializer,
    CustomerLedgerEntrySerializer,
    CustomerPaymentCreateSerializer,
    CustomerPaymentSerializer,
)
from operations.models import AuctionSale, AuctionSaleLine, Container, Customer, GatePass, PartInventory


class UserStampedMixin:
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class ExpenseViewSet(UserStampedMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['expense_date', 'category', 'payment_method', 'title', 'payee']
    search_fields = ['title', 'category', 'payee', 'payment_method', 'reference', 'notes']
    ordering_fields = ['expense_date', 'amount', 'title', 'category', 'created_at']

    def get_queryset(self):
        queryset = Expense.objects.all()
        start = parse_date(self.request.query_params.get('start', ''))
        end = parse_date(self.request.query_params.get('end', ''))
        if start:
            queryset = queryset.filter(expense_date__gte=start)
        if end:
            queryset = queryset.filter(expense_date__lte=end)
        return queryset.order_by('-expense_date', '-created_at')

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        bounds = Expense.objects.aggregate(oldest=Min('expense_date'), latest=Max('expense_date'))
        oldest = bounds['oldest']
        latest = bounds['latest']
        start = parse_date(request.query_params.get('start', '')) or oldest
        end = parse_date(request.query_params.get('end', '')) or latest
        if start and end and start > end:
            raise DRFValidationError({'end': 'End date must be on or after start date.'})

        granularity = request.query_params.get('granularity', 'month').lower()
        if granularity not in {'day', 'week', 'month', 'year'}:
            raise DRFValidationError({'granularity': 'Use day, week, month, or year.'})

        queryset = Expense.objects.all()
        if start:
            queryset = queryset.filter(expense_date__gte=start)
        if end:
            queryset = queryset.filter(expense_date__lte=end)

        totals = queryset.aggregate(
            total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField(max_digits=16, decimal_places=2)),
            average=Coalesce(Avg('amount'), Value(Decimal('0.00')), output_field=DecimalField(max_digits=16, decimal_places=2)),
            largest=Coalesce(Max('amount'), Value(Decimal('0.00')), output_field=DecimalField(max_digits=16, decimal_places=2)),
            count=Count('id'),
        )

        truncators = {'week': TruncWeek, 'month': TruncMonth, 'year': TruncYear}
        if granularity == 'day':
            period_rows = queryset.values(period=F('expense_date')).annotate(total=Sum('amount'), count=Count('id')).order_by('period')
        else:
            period_rows = queryset.annotate(period=truncators[granularity]('expense_date')).values('period').annotate(total=Sum('amount'), count=Count('id')).order_by('period')

        def period_value(value):
            if hasattr(value, 'date'):
                value = value.date()
            return value.isoformat()

        return Response({
            'generated_at': timezone.localtime(),
            'date_bounds': {
                'oldest_expense_date': oldest,
                'latest_expense_date': latest,
                'start': start,
                'end': end,
                'granularity': granularity,
            },
            'totals': totals,
            'selected': [
                {'period': period_value(row['period']), 'total_amount': row['total'], 'count': row['count']}
                for row in period_rows
            ],
            'categories': list(queryset.values('category').annotate(total_amount=Sum('amount'), count=Count('id')).order_by('-total_amount', 'category')),
            'payment_methods': list(queryset.values('payment_method').annotate(total_amount=Sum('amount'), count=Count('id')).order_by('-total_amount', 'payment_method')),
        })


class ChequeStatusViewSet(UserStampedMixin, viewsets.ModelViewSet):
    queryset = ChequeStatus.objects.all()
    serializer_class = ChequeStatusSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['is_active', 'balance_effect']
    search_fields = ['name']
    ordering_fields = ['name', 'created_at']


class ChequeViewSet(viewsets.ModelViewSet):
    queryset = Cheque.objects.select_related('customer', 'status', 'sale').prefetch_related(
        'settlement_allocations__sale',
    )
    serializer_class = ChequeSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['customer', 'status', 'bank_name', 'sale']
    search_fields = ['cheque_number', 'customer__name', 'bank_name', 'account_title']
    ordering_fields = ['cheque_date', 'expiry_date', 'received_date', 'amount']

    @action(detail=True, methods=['post'], url_path='change-status')
    def change_status(self, request, pk=None):
        serializer = ChequeStatusChangeSerializer(
            data=request.data,
            context={'request': request, 'cheque': self.get_object()},
        )
        serializer.is_valid(raise_exception=True)
        cheque = serializer.save()
        return Response(ChequeSerializer(cheque, context={'request': request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        history = self.get_object().status_history.select_related('from_status', 'to_status')
        return Response(ChequeStatusHistorySerializer(history, many=True).data)


class CustomerPaymentViewSet(viewsets.ModelViewSet):
    http_method_names = ['get', 'post', 'head', 'options']
    permission_classes = [FinancePermission]
    filterset_fields = ['customer', 'kind', 'payment_date']
    search_fields = ['payment_number', 'customer__name', 'reference', 'notes', 'components__cheque__cheque_number']
    ordering_fields = ['payment_date', 'created_at', 'total_amount']

    def get_queryset(self):
        return (
            CustomerPayment.objects
            .select_related('customer')
            .prefetch_related(
                'components__cheque__status',
                'components__allocations__sale',
                'components__allocations__opening_balance',
                'targets__sale',
                'targets__opening_balance',
            )
            .order_by('-payment_date', '-created_at')
        )

    def get_serializer_class(self):
        if self.action in {'create', 'update', 'partial_update'}:
            return CustomerPaymentCreateSerializer
        return CustomerPaymentSerializer


class LedgerEntryViewSet(UserStampedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = CustomerLedgerEntry.objects.select_related('customer', 'sale', 'cheque', 'payment')
    serializer_class = CustomerLedgerEntrySerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['customer', 'entry_type', 'sale', 'cheque']
    search_fields = ['customer__name', 'description']
    ordering_fields = ['entry_date', 'created_at', 'debit', 'credit']


class CustomerBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerBalanceSerializer
    permission_classes = [FinancePermission]
    search_fields = ['name', 'phone']
    ordering_fields = ['name', 'created_at']

    def get_queryset(self):
        sale_lines = AuctionSaleLine.objects.select_related('item', 'inventory_batch', 'inventory_batch__container')
        allocations = ChequeSettlementAllocation.objects.select_related('cheque', 'sale')
        payment_allocations = CustomerPaymentAllocation.objects.select_related('component__payment', 'sale')
        sales = (
            AuctionSale.objects
            .filter(is_cancelled=False)
            .prefetch_related(
                Prefetch('lines', queryset=sale_lines),
                Prefetch('cheque_allocations', queryset=allocations),
                Prefetch('payment_allocations', queryset=payment_allocations),
            )
            .order_by('sale_date', 'created_at')
        )
        return (
            Customer.objects
            .filter(is_active=True)
            .annotate(
                ledger_debit=Coalesce(
                    Sum('ledger_entries__debit'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
                ledger_credit=Coalesce(
                    Sum('ledger_entries__credit'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                ),
            )
            .prefetch_related(Prefetch('auction_sales', queryset=sales))
            .order_by('name')
        )


class CurrencyViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CurrencySerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['is_active']
    search_fields = ['code', 'name', 'symbol']
    ordering_fields = ['code', 'name']

    def get_queryset(self):
        return Currency.objects.prefetch_related(
            'purchases__repayments', 'opening_balances', 'spending_entries',
        ).order_by('code')


class CurrencyCreditorViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CurrencyCreditorSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['is_active']
    search_fields = ['name', 'phone', 'address', 'notes']
    ordering_fields = ['name', 'created_at']

    def get_queryset(self):
        repayment_queryset = CurrencyCreditorRepayment.objects.order_by('repayment_date', 'created_at')
        purchase_queryset = (
            CurrencyPurchase.objects
            .filter(purchase_type=CurrencyPurchase.PurchaseType.CREDIT)
            .select_related('currency')
            .prefetch_related(Prefetch('repayments', queryset=repayment_queryset))
            .order_by('purchase_date', 'created_at')
        )
        return CurrencyCreditor.objects.prefetch_related(
            Prefetch('credit_purchases', queryset=purchase_queryset),
        ).order_by('name')

    def destroy(self, request, *args, **kwargs):
        creditor = self.get_object()
        if creditor.credit_purchases.exists():
            return Response(
                {'detail': 'This creditor has currency purchase history and cannot be deleted. Mark it inactive instead.'},
                status=status.HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['get'], url_path='statement')
    def statement(self, request, pk=None):
        return currency_creditor_statement_pdf_response(self.get_object())


class CurrencyCreditorRepaymentViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CurrencyCreditorRepaymentSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['purchase', 'purchase__creditor', 'purchase__currency', 'repayment_date']
    search_fields = ['purchase__creditor__name', 'purchase__currency__code', 'reference', 'notes']
    ordering_fields = ['repayment_date', 'amount', 'total_cost', 'exchange_rate']

    def get_queryset(self):
        return CurrencyCreditorRepayment.objects.select_related(
            'purchase', 'purchase__creditor', 'purchase__currency',
        ).order_by('-repayment_date', '-created_at')


class CurrencyPurchaseViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CurrencyPurchaseSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['currency', 'purchase_type', 'creditor', 'purchase_date', 'due_date']
    search_fields = ['currency__code', 'currency__name', 'creditor__name', 'source', 'reference', 'notes']
    ordering_fields = ['purchase_date', 'amount', 'total_cost', 'acquisition_rate']

    def get_queryset(self):
        return CurrencyPurchase.objects.select_related('currency', 'creditor').prefetch_related('repayments').order_by('-purchase_date', '-created_at')

    def perform_destroy(self, instance):
        try:
            delete_currency_purchase(instance=instance)
        except DjangoValidationError as error:
            raise DRFValidationError(error.message_dict) from error


class CurrencyOpeningBalanceViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CurrencyOpeningBalanceSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['currency', 'entry_date']
    search_fields = ['currency__code', 'currency__name', 'source', 'reference', 'notes']
    ordering_fields = ['entry_date', 'amount', 'total_cost', 'acquisition_rate']

    def get_queryset(self):
        return CurrencyOpeningBalance.objects.select_related('currency').order_by('-entry_date', '-created_at')

    def perform_destroy(self, instance):
        try:
            delete_currency_acquisition(instance=instance)
        except DjangoValidationError as error:
            raise DRFValidationError(error.message_dict) from error


class CurrencySpendingViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CurrencySpendingSerializer
    permission_classes = [FinancePermission]
    filterset_fields = ['currency', 'spending_date']
    search_fields = ['currency__code', 'currency__name', 'purpose', 'reference', 'notes']
    ordering_fields = ['spending_date', 'amount']

    def get_queryset(self):
        return CurrencySpending.objects.select_related('currency').order_by('-spending_date', '-created_at')


@api_view(['GET'])
@permission_classes([DashboardPermission])
def dashboard_summary(request):
    today = timezone.localdate()
    ledger_totals = CustomerLedgerEntry.objects.aggregate(debit=Sum('debit'), credit=Sum('credit'))
    receivable = (ledger_totals['debit'] or 0) - (ledger_totals['credit'] or 0)
    parts = PartInventory.objects.annotate(
        sold_quantity=Coalesce(
            Sum('sale_lines__quantity', filter=Q(sale_lines__sale__is_cancelled=False)),
            Value(0),
        ),
    )
    available_parts = sum(1 for part in parts if part.quantity > part.sold_quantity)
    sold_out_parts = parts.count() - available_parts
    cheque_counts = Cheque.objects.values('status__name').annotate(count=Count('id'))
    pending_in_date_cheques = (
        Cheque.objects
        .select_related('customer', 'status')
        .filter(
            cheque_date__lte=today,
            expiry_date__gte=today,
            status__balance_effect=ChequeStatus.BalanceEffect.NONE,
        )
        .exclude(status__name__iexact='Bounced')
        .order_by('cheque_date', 'expiry_date', 'customer__name')[:8]
    )
    cheque_amounts_by_status = Cheque.objects.values('status__name').annotate(total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField(max_digits=14, decimal_places=2)))

    return Response({
        'containers': Container.objects.count(),
        'items': {
            'total': PartInventory.objects.count(),
            'by_status': {'available': available_parts, 'sold_out': sold_out_parts},
        },
        'auction_sales': AuctionSale.objects.filter(is_cancelled=False).count(),
        'gate_passes': {
            'issued': GatePass.objects.filter(status=GatePass.Status.ISSUED).count(),
            'not_printed': GatePass.objects.filter(print_status=GatePass.PrintStatus.NOT_PRINTED).count(),
            'printed': GatePass.objects.filter(print_status=GatePass.PrintStatus.PRINTED).count(),
        },
        'cheques_by_status': {row['status__name']: row['count'] for row in cheque_counts},
        'cheque_amounts_by_status': {row['status__name']: row['total'] for row in cheque_amounts_by_status},
        'pending_in_date_cheques': [
            {
                'id': str(cheque.id),
                'cheque_number': cheque.cheque_number,
                'customer_name': cheque.customer.name,
                'bank_name': cheque.bank_name,
                'amount': cheque.amount,
                'cheque_date': cheque.cheque_date,
                'expiry_date': cheque.expiry_date,
                'status_name': cheque.status.name,
            }
            for cheque in pending_in_date_cheques
        ],
        'creditors': {
            'count': Customer.objects.annotate(
                debit_total=Coalesce(Sum('ledger_entries__debit'), Value(Decimal('0.00')), output_field=DecimalField(max_digits=14, decimal_places=2)),
                credit_total=Coalesce(Sum('ledger_entries__credit'), Value(Decimal('0.00')), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ).filter(debit_total__gt=F('credit_total')).count(),
            'total_outstanding': receivable,
        },
        'customer_receivable': receivable,
    })


@api_view(['GET'])
def credit_report(request):
    if not has_tab_access(request.user, 'customers'):
        raise PermissionDenied('You do not have access to customer balance reports.')
    report = build_credit_report()
    export_format = request.query_params.get('export', 'json').lower()
    section = request.query_params.get('section', 'combined').lower()
    if section not in {'summary', 'aging', 'outstanding', 'combined'}:
        raise DRFValidationError({'section': 'Choose summary, aging, outstanding, or combined.'})
    if export_format == 'csv':
        return credit_report_csv_response(report, section=section)
    if export_format == 'pdf':
        return credit_report_pdf_response(report, section=section)
    return Response(credit_report_payload(report))


@api_view(['GET'])
def customer_statement(request, customer_id):
    if not has_tab_access(request.user, 'customers'):
        raise PermissionDenied('You do not have access to customer statements.')
    report = build_customer_statement(customer_id=customer_id)
    report_type = request.query_params.get('report', 'combined').lower()
    if report_type not in {'aging', 'transactions', 'outstanding', 'combined'}:
        raise DRFValidationError({'report': 'Choose aging, transactions, outstanding, or combined.'})
    credit_report_data = build_credit_report()
    credit_row = next((row for row in credit_report_data.customers if row['id'] == str(customer_id)), None)
    return customer_statement_pdf_response(report, report_type=report_type, credit_row=credit_row)


@api_view(['GET'])
def customer_receivable_list(request, customer_id):
    if not has_tab_access(request.user, 'customers'):
        raise PermissionDenied('You do not have access to customer balances.')
    customer = get_object_or_404(Customer, id=customer_id)
    rows = customer_receivables(customer=customer)
    return Response({
        'customer': str(customer.id),
        'outstanding_total': sum((row['outstanding_amount'] for row in rows), Decimal('0.00')),
        'results': rows,
    })


@api_view(['GET'])
def daily_payment_report(request):
    if not has_tab_access(request.user, 'customers'):
        raise PermissionDenied('You do not have access to customer payment reports.')
    raw_date = request.query_params.get('date') or str(timezone.localdate())
    report_date = parse_date(raw_date)
    if report_date is None:
        raise DRFValidationError({'date': 'Use a valid date in YYYY-MM-DD format.'})
    if report_date > timezone.localdate():
        raise DRFValidationError({'date': 'Daily payment reports cannot be generated for a future date.'})
    report = build_daily_payment_report(report_date=report_date)
    if request.query_params.get('export', '').lower() == 'pdf':
        return daily_payment_report_pdf_response(report)
    return Response(daily_payment_report_payload(report))
