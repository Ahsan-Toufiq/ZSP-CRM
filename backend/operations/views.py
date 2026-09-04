from decimal import Decimal

from django.db.models import Count, DecimalField, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT

from accounts.permissions import OperationsPermission
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass
from operations.serializers import (
    AuctionSaleCreateSerializer,
    AuctionSaleLineReadSerializer,
    AuctionSaleSerializer,
    AuctionSaleUpdateSerializer,
    ContainerItemSerializer,
    ContainerSerializer,
    CustomerSerializer,
    GatePassCreateSerializer,
    GatePassSerializer,
    GatePassUpdateSerializer,
)
from operations.services import mark_gate_pass_printed, verify_gate_pass


class UserStampedMixin:
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class CustomerViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [OperationsPermission]
    filterset_fields = ['is_active', 'customer_type']
    search_fields = ['name', 'phone', 'email', 'cnic_or_tax_id']
    ordering_fields = ['name', 'created_at']

    def get_queryset(self):
        return Customer.objects.annotate(
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
        ).order_by('name')

    def destroy(self, request, *args, **kwargs):
        customer = self.get_object()
        blocking_counts = {
            'auction_sales': customer.auction_sales.count(),
            'cheques': customer.cheques.count(),
            'ledger_entries': customer.ledger_entries.count(),
        }
        if any(blocking_counts.values()):
            return Response(
                {
                    'detail': 'This customer has transactions and cannot be deleted. Mark the customer inactive instead.',
                    'blocking_records': blocking_counts,
                },
                status=HTTP_409_CONFLICT,
            )
        return super().destroy(request, *args, **kwargs)


class ContainerViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = ContainerSerializer
    permission_classes = [OperationsPermission]
    filterset_fields = ['status', 'origin_country']
    search_fields = ['reference', 'supplier_name', 'manifest_notes']
    ordering_fields = ['arrival_date', 'created_at', 'reference']

    def get_queryset(self):
        return Container.objects.annotate(item_count=Count('items')).order_by('-arrival_date', '-created_at')


class ContainerItemViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = ContainerItemSerializer
    permission_classes = [OperationsPermission]
    filterset_fields = ['container', 'status', 'category', 'condition']
    search_fields = ['lot_number', 'part_name', 'part_number', 'description', 'category']
    ordering_fields = ['lot_number', 'part_name', 'created_at']

    def get_queryset(self):
        return (
            ContainerItem.objects
            .select_related('container')
            .annotate(
                sold_quantity_total=Coalesce(
                    Sum(
                        'sale_lines__quantity',
                        filter=Q(sale_lines__sale__is_cancelled=False),
                    ),
                    Value(0),
                    output_field=IntegerField(),
                ),
            )
            .order_by('container__reference', 'lot_number')
        )

    def perform_destroy(self, instance):
        if instance.status != ContainerItem.Status.AVAILABLE:
            raise ValidationError({'item': 'Only available inventory can be deleted.'})
        instance.delete()

    @action(detail=False, methods=['get'], url_path='parts-inventory')
    def parts_inventory(self, request):
        rows = (
            ContainerItem.objects
            .values('part_name', 'part_number', 'category', 'unit')
            .annotate(total_quantity=Sum('quantity'))
            .order_by('part_name', 'part_number')
        )
        sale_totals = (
            AuctionSaleLine.objects
            .filter(sale__is_cancelled=False)
            .values('item__part_name', 'item__part_number', 'item__category', 'item__unit')
            .annotate(sold_quantity=Sum('quantity'))
        )
        sold_by_key = {
            (
                row['item__part_name'],
                row['item__part_number'],
                row['item__category'],
                row['item__unit'],
            ): row['sold_quantity'] or 0
            for row in sale_totals
        }
        data = []
        for row in rows:
            key = (row['part_name'], row['part_number'], row['category'], row['unit'])
            sold_quantity = sold_by_key.get(key, 0)
            total_quantity = row['total_quantity'] or 0
            data.append({
                'part_name': row['part_name'],
                'part_number': row['part_number'],
                'category': row['category'],
                'unit': row['unit'],
                'total_quantity': total_quantity,
                'sold_quantity': sold_quantity,
                'available_quantity': max(total_quantity - sold_quantity, 0),
            })
        return Response(data)


class AuctionSaleViewSet(viewsets.ModelViewSet):
    queryset = AuctionSale.objects.select_related('customer').prefetch_related('lines__item__container', 'gate_pass')
    permission_classes = [OperationsPermission]
    filterset_fields = ['payment_type', 'is_cancelled', 'customer']
    search_fields = ['sale_number', 'customer__name', 'notes']
    ordering_fields = ['sale_date', 'created_at', 'total_amount']

    def get_serializer_class(self):
        if self.action == 'create':
            return AuctionSaleCreateSerializer
        if self.action in {'update', 'partial_update'}:
            return AuctionSaleUpdateSerializer
        return AuctionSaleSerializer

    @action(detail=False, methods=['get'], url_path='sold-without-gate-pass')
    def sold_without_gate_pass(self, request):
        queryset = (
            AuctionSaleLine.objects
            .select_related('sale', 'sale__customer', 'item', 'item__container')
            .filter(gate_pass_line__isnull=True, sale__is_cancelled=False, item__status=ContainerItem.Status.SOLD)
            .order_by('-sale__sale_date')
        )
        page = self.paginate_queryset(queryset)
        serializer = AuctionSaleLineReadSerializer(page or queryset, many=True, context={'request': request})
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class GatePassViewSet(viewsets.ModelViewSet):
    queryset = GatePass.objects.prefetch_related('lines__sale_line__item__container', 'lines__sale_line__sale')
    permission_classes = [OperationsPermission]
    filterset_fields = ['status']
    search_fields = ['gate_pass_number', 'issued_to_name', 'issued_to_phone', 'vehicle_number', 'driver_name']
    ordering_fields = ['issued_at', 'created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return GatePassCreateSerializer
        if self.action in {'update', 'partial_update'}:
            return GatePassUpdateSerializer
        return GatePassSerializer

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        gate_pass = self.get_object()
        gate_pass = verify_gate_pass(user=request.user, gate_pass=gate_pass)
        return Response(GatePassSerializer(gate_pass, context={'request': request}).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='mark-printed')
    def mark_printed(self, request, pk=None):
        gate_pass = self.get_object()
        gate_pass = mark_gate_pass_printed(user=request.user, gate_pass=gate_pass)
        return Response(GatePassSerializer(gate_pass, context={'request': request}).data, status=status.HTTP_200_OK)
