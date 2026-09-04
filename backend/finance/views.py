from decimal import Decimal

from django.db.models import Count, DecimalField, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from accounts.permissions import DashboardPermission, FinancePermission
from finance.models import Cheque, ChequeSettlementAllocation, ChequeStatus, CustomerLedgerEntry
from finance.serializers import (
    ChequeSerializer,
    ChequeStatusChangeSerializer,
    ChequeStatusHistorySerializer,
    ChequeStatusSerializer,
    CustomerBalanceSerializer,
    CustomerLedgerEntrySerializer,
)
from operations.models import AuctionSale, AuctionSaleLine, Container, Customer, GatePass, PartInventory


class UserStampedMixin:
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


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


class LedgerEntryViewSet(UserStampedMixin, viewsets.ReadOnlyModelViewSet):
    queryset = CustomerLedgerEntry.objects.select_related('customer', 'sale', 'cheque')
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
        sale_lines = AuctionSaleLine.objects.select_related('item')
        allocations = ChequeSettlementAllocation.objects.select_related('cheque', 'sale')
        sales = (
            AuctionSale.objects
            .filter(is_cancelled=False)
            .prefetch_related(
                Prefetch('lines', queryset=sale_lines),
                Prefetch('cheque_allocations', queryset=allocations),
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


@api_view(['GET'])
@permission_classes([DashboardPermission])
def dashboard_summary(request):
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
        'customer_receivable': receivable,
    })
