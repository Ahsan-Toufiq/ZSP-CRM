from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from core_models import UserStampedModel


class Customer(UserStampedModel):
    class CustomerType(models.TextChoices):
        INDIVIDUAL = 'individual', 'Individual'
        BUSINESS = 'business', 'Business'

    name = models.CharField(max_length=180)
    customer_type = models.CharField(
        max_length=20,
        choices=CustomerType.choices,
        default=CustomerType.INDIVIDUAL,
    )
    phone = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    cnic_or_tax_id = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['phone']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self) -> str:
        return self.name


class Container(UserStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        RECEIVING = 'receiving', 'Receiving'
        READY_FOR_AUCTION = 'ready_for_auction', 'Ready for auction'
        CLOSED = 'closed', 'Closed'

    reference = models.CharField(max_length=80, unique=True)
    origin_country = models.CharField(max_length=80, blank=True)
    supplier_name = models.CharField(max_length=180, blank=True)
    arrival_date = models.DateField(null=True, blank=True)
    manifest_notes = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    added_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        ordering = ['-arrival_date', '-created_at']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['status']),
            models.Index(fields=['arrival_date']),
        ]

    def __str__(self) -> str:
        return self.reference


class ContainerItem(UserStampedModel):
    class Condition(models.TextChoices):
        UNKNOWN = 'unknown', 'Unknown'
        USED = 'used', 'Used'
        NEW = 'new', 'New'
        DAMAGED = 'damaged', 'Damaged'

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        SOLD = 'sold', 'Sold'
        GATE_PASS_ISSUED = 'gate_pass_issued', 'Gate pass issued'
        RELEASED = 'released', 'Released'
        VOID = 'void', 'Void'

    container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name='items')
    lot_number = models.CharField(max_length=80, blank=True)
    part_name = models.CharField(max_length=180)
    part_number = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    condition = models.CharField(max_length=80, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default='piece')
    reserve_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    raw_unit_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        ordering = ['container__reference', 'part_name', 'lot_number']
        indexes = [
            models.Index(fields=['part_name']),
            models.Index(fields=['part_number']),
            models.Index(fields=['category']),
        ]

    def __str__(self) -> str:
        lot = f'{self.lot_number} - ' if self.lot_number else ''
        return f'{self.container.reference} / {lot}{self.part_name}'


class PartInventory(UserStampedModel):
    part_name = models.CharField(max_length=180)
    part_number = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=120, blank=True)
    condition = models.CharField(max_length=80, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=30, default='piece')
    reserve_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['part_name', 'part_number']
        constraints = [
            models.UniqueConstraint(
                fields=['part_name', 'part_number', 'category', 'condition', 'unit'],
                name='unique_sellable_part_inventory',
            ),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name='part_inventory_quantity_non_negative'),
        ]
        indexes = [
            models.Index(fields=['part_name']),
            models.Index(fields=['part_number']),
            models.Index(fields=['category']),
        ]

    def __str__(self) -> str:
        return self.part_name


class InventoryBatch(UserStampedModel):
    item = models.ForeignKey(PartInventory, on_delete=models.PROTECT, related_name='batches')
    container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name='inventory_batches', null=True, blank=True)
    container_item = models.OneToOneField(ContainerItem, on_delete=models.PROTECT, related_name='inventory_batch', null=True, blank=True)
    source_label = models.CharField(max_length=180, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    raw_unit_cost = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['item__part_name', 'container__reference', 'created_at']
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gte=0), name='inventory_batch_quantity_non_negative'),
        ]
        indexes = [
            models.Index(fields=['item']),
            models.Index(fields=['container']),
            models.Index(fields=['source_label']),
        ]

    def __str__(self) -> str:
        source = self.container.reference if self.container_id else self.source_label or 'Manual'
        return f'{self.item.part_name} / {source}'


class AuctionSale(UserStampedModel):
    class PaymentType(models.TextChoices):
        CASH = 'cash', 'Cash'
        CREDIT = 'credit', 'Credit'
        CHEQUE = 'cheque', 'Cheque'
        MIXED = 'mixed', 'Mixed'

    sale_number = models.CharField(max_length=40, unique=True)
    sale_date = models.DateField()
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='auction_sales',
        null=True,
        blank=True,
    )
    payment_type = models.CharField(max_length=20, choices=PaymentType.choices)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    is_cancelled = models.BooleanField(default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cancelled_auction_sales',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-sale_date', '-created_at']
        indexes = [
            models.Index(fields=['sale_number']),
            models.Index(fields=['sale_date']),
            models.Index(fields=['payment_type']),
            models.Index(fields=['is_cancelled']),
        ]

    def clean(self):
        if self.payment_type != self.PaymentType.CASH and not self.customer_id:
            raise ValidationError({'customer': 'Customer is required for credit, cheque, and mixed sales.'})

    def __str__(self) -> str:
        return self.sale_number


class AuctionSaleLine(UserStampedModel):
    sale = models.ForeignKey(AuctionSale, on_delete=models.PROTECT, related_name='lines')
    item = models.ForeignKey(PartInventory, on_delete=models.PROTECT, related_name='sale_lines')
    inventory_batch = models.ForeignKey(
        InventoryBatch,
        on_delete=models.PROTECT,
        related_name='sale_lines',
        null=True,
        blank=True,
    )
    quantity = models.PositiveIntegerField(default=1)
    sold_price = models.DecimalField(max_digits=14, decimal_places=2)
    raw_unit_cost_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    net_unit_cost_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['sale__sale_number', 'item__part_name']
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name='sale_line_quantity_positive'),
        ]
        indexes = [
            models.Index(fields=['sold_price']),
            models.Index(fields=['item']),
            models.Index(fields=['inventory_batch']),
        ]

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be greater than zero.'})

    def __str__(self) -> str:
        return f'{self.sale.sale_number} / {self.item.part_name}'


class GatePass(UserStampedModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        ISSUED = 'issued', 'Issued'
        VERIFIED = 'verified', 'Verified'
        CANCELLED = 'cancelled', 'Cancelled'

    class PrintStatus(models.TextChoices):
        NOT_PRINTED = 'not_printed', 'Not printed'
        PRINTED = 'printed', 'Printed'

    gate_pass_number = models.CharField(max_length=40, unique=True)
    sale = models.OneToOneField(
        AuctionSale,
        on_delete=models.PROTECT,
        related_name='gate_pass',
        null=True,
        blank=True,
    )
    issued_to_name = models.CharField(max_length=180)
    issued_to_phone = models.CharField(max_length=40, blank=True)
    vehicle_number = models.CharField(max_length=80, blank=True)
    driver_name = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ISSUED)
    print_status = models.CharField(max_length=20, choices=PrintStatus.choices, default=PrintStatus.NOT_PRINTED)
    issued_at = models.DateTimeField()
    printed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='verified_gate_passes',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['-issued_at']
        indexes = [
            models.Index(fields=['gate_pass_number']),
            models.Index(fields=['status']),
            models.Index(fields=['issued_at']),
        ]

    def __str__(self) -> str:
        return self.gate_pass_number


class GatePassLine(UserStampedModel):
    gate_pass = models.ForeignKey(GatePass, on_delete=models.PROTECT, related_name='lines')
    sale_line = models.OneToOneField(AuctionSaleLine, on_delete=models.PROTECT, related_name='gate_pass_line')

    class Meta:
        ordering = ['gate_pass__gate_pass_number']
        constraints = [
            models.UniqueConstraint(fields=['sale_line'], name='unique_gate_pass_per_sold_item'),
        ]

    def clean(self):
        if self.sale_line_id and self.sale_line.sale.is_cancelled:
            raise ValidationError({'sale_line': 'Cannot issue a gate pass for a cancelled sale.'})

    def __str__(self) -> str:
        return f'{self.gate_pass.gate_pass_number} / {self.sale_line.item.part_name}'

# Create your models here.
