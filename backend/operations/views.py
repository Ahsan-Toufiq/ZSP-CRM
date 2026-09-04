from decimal import Decimal

from django.db.models import Count, DecimalField, IntegerField, OuterRef, Prefetch, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.status import HTTP_409_CONFLICT

from accounts.permissions import OperationsPermission
from finance.models import Cheque, CustomerLedgerEntry
from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, PartInventory
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
    PartInventorySerializer,
)
from operations.services import apply_container_inventory_delta, mark_gate_pass_printed, sold_quantity_for_item, verify_gate_pass


def sale_line_queryset():
    return (
        AuctionSaleLine.objects
        .select_related('item', 'sale', 'sale__customer')
        .annotate(
            item_sold_quantity_total=Coalesce(
                Sum(
                    'item__sale_lines__quantity',
                    filter=Q(item__sale_lines__sale__is_cancelled=False),
                ),
                Value(0),
                output_field=IntegerField(),
            ),
        )
    )


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
        ledger_totals = CustomerLedgerEntry.objects.filter(customer=OuterRef('pk')).values('customer').annotate(
            debit_total=Sum('debit'),
            credit_total=Sum('credit'),
            entry_count=Count('id'),
        )
        sale_counts = AuctionSale.objects.filter(customer=OuterRef('pk')).values('customer').annotate(count=Count('id'))
        cheque_counts = Cheque.objects.filter(customer=OuterRef('pk')).values('customer').annotate(count=Count('id'))
        return Customer.objects.annotate(
            ledger_debit=Coalesce(Subquery(ledger_totals.values('debit_total')[:1]), Value(Decimal('0.00')), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ledger_credit=Coalesce(Subquery(ledger_totals.values('credit_total')[:1]), Value(Decimal('0.00')), output_field=DecimalField(max_digits=14, decimal_places=2)),
            ledger_entry_count=Coalesce(Subquery(ledger_totals.values('entry_count')[:1]), Value(0), output_field=IntegerField()),
            auction_sale_count=Coalesce(Subquery(sale_counts.values('count')[:1]), Value(0), output_field=IntegerField()),
            cheque_count=Coalesce(Subquery(cheque_counts.values('count')[:1]), Value(0), output_field=IntegerField()),
        ).order_by('name')

    def destroy(self, request, *args, **kwargs):
        customer = self.get_object()
        blocking_counts = {
            'auction_sales': getattr(customer, 'auction_sale_count', customer.auction_sales.count()),
            'cheques': getattr(customer, 'cheque_count', customer.cheques.count()),
            'ledger_entries': getattr(customer, 'ledger_entry_count', customer.ledger_entries.count()),
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
            .order_by('container__reference', 'part_name', 'lot_number')
        )

    def perform_destroy(self, instance):
        before = {
            'part_name': instance.part_name,
            'part_number': instance.part_number or '',
            'category': instance.category or '',
            'condition': instance.condition or '',
            'unit': instance.unit or 'piece',
            'quantity': instance.quantity,
            'reserve_price': instance.reserve_price,
            'description': instance.description or '',
        }
        apply_container_inventory_delta(user=self.request.user, before=before)
        instance.delete()


class PartInventoryViewSet(UserStampedMixin, viewsets.ModelViewSet):
    serializer_class = PartInventorySerializer
    permission_classes = [OperationsPermission]
    filterset_fields = ['category', 'condition', 'unit']
    search_fields = ['part_name', 'part_number', 'description', 'category']
    ordering_fields = ['part_name', 'part_number', 'created_at', 'quantity']

    def get_queryset(self):
        return (
            PartInventory.objects
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
            .order_by('part_name', 'part_number')
        )

    def perform_destroy(self, instance):
        sold = sold_quantity_for_item(instance)
        if sold:
            raise ValidationError({'part': f'This part has {sold} sold unit(s) and cannot be deleted.'})
        instance.delete()


class AuctionSaleViewSet(viewsets.ModelViewSet):
    permission_classes = [OperationsPermission]
    filterset_fields = ['payment_type', 'is_cancelled', 'customer']
    search_fields = ['sale_number', 'customer__name', 'notes']
    ordering_fields = ['sale_date', 'created_at', 'total_amount']

    def get_queryset(self):
        return (
            AuctionSale.objects
            .select_related('customer')
            .prefetch_related(Prefetch('lines', queryset=sale_line_queryset()), 'gate_pass')
            .order_by('-sale_date', '-created_at')
        )

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
            .select_related('sale', 'sale__customer', 'item')
            .annotate(
                item_sold_quantity_total=Coalesce(
                    Sum(
                        'item__sale_lines__quantity',
                        filter=Q(item__sale_lines__sale__is_cancelled=False),
                    ),
                    Value(0),
                    output_field=IntegerField(),
                ),
            )
            .filter(gate_pass_line__isnull=True, sale__is_cancelled=False)
            .order_by('-sale__sale_date')
        )
        page = self.paginate_queryset(queryset)
        serializer = AuctionSaleLineReadSerializer(page or queryset, many=True, context={'request': request})
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class GatePassViewSet(viewsets.ModelViewSet):
    permission_classes = [OperationsPermission]
    filterset_fields = ['status']
    search_fields = ['gate_pass_number', 'issued_to_name', 'issued_to_phone', 'vehicle_number', 'driver_name']
    ordering_fields = ['issued_at', 'created_at']

    def get_queryset(self):
        return (
            GatePass.objects
            .select_related('sale', 'verified_by')
            .prefetch_related(Prefetch('lines__sale_line', queryset=sale_line_queryset()))
            .order_by('-issued_at')
        )

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
