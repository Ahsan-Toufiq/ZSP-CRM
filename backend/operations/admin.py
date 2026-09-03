from django.contrib import admin

from operations.models import AuctionSale, AuctionSaleLine, Container, ContainerItem, Customer, GatePass, GatePassLine


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_type', 'phone', 'is_active')
    search_fields = ('name', 'phone', 'email', 'cnic_or_tax_id')
    list_filter = ('customer_type', 'is_active')


class ContainerItemInline(admin.TabularInline):
    model = ContainerItem
    extra = 0
    fields = ('lot_number', 'part_name', 'part_number', 'category', 'condition', 'quantity', 'status')
    readonly_fields = ('status',)


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ('reference', 'origin_country', 'supplier_name', 'arrival_date', 'status')
    search_fields = ('reference', 'supplier_name')
    list_filter = ('status', 'origin_country')
    inlines = [ContainerItemInline]


@admin.register(ContainerItem)
class ContainerItemAdmin(admin.ModelAdmin):
    list_display = ('lot_number', 'part_name', 'container', 'category', 'condition', 'quantity', 'status')
    search_fields = ('lot_number', 'part_name', 'part_number')
    list_filter = ('status', 'condition', 'category')


class AuctionSaleLineInline(admin.TabularInline):
    model = AuctionSaleLine
    extra = 0
    readonly_fields = ('item', 'sold_price')


@admin.register(AuctionSale)
class AuctionSaleAdmin(admin.ModelAdmin):
    list_display = ('sale_number', 'sale_date', 'customer', 'payment_type', 'total_amount', 'is_cancelled')
    search_fields = ('sale_number', 'customer__name')
    list_filter = ('payment_type', 'is_cancelled')
    inlines = [AuctionSaleLineInline]


class GatePassLineInline(admin.TabularInline):
    model = GatePassLine
    extra = 0


@admin.register(GatePass)
class GatePassAdmin(admin.ModelAdmin):
    list_display = ('gate_pass_number', 'issued_to_name', 'vehicle_number', 'status', 'print_status', 'issued_at', 'printed_at', 'verified_at')
    search_fields = ('gate_pass_number', 'issued_to_name', 'vehicle_number')
    list_filter = ('status', 'print_status')
    inlines = [GatePassLineInline]

# Register your models here.
