from django.contrib import admin

from finance.models import Cheque, ChequeStatus, ChequeStatusHistory, CustomerLedgerEntry


@admin.register(ChequeStatus)
class ChequeStatusAdmin(admin.ModelAdmin):
    list_display = ('name', 'balance_effect', 'is_system', 'is_active')
    list_filter = ('balance_effect', 'is_system', 'is_active')
    search_fields = ('name',)


class ChequeStatusHistoryInline(admin.TabularInline):
    model = ChequeStatusHistory
    extra = 0
    readonly_fields = ('from_status', 'to_status', 'notes', 'created_at')


@admin.register(Cheque)
class ChequeAdmin(admin.ModelAdmin):
    list_display = ('cheque_number', 'customer', 'bank_name', 'amount', 'cheque_date', 'expiry_date', 'status')
    search_fields = ('cheque_number', 'customer__name', 'bank_name')
    list_filter = ('status', 'bank_name')
    inlines = [ChequeStatusHistoryInline]


@admin.register(CustomerLedgerEntry)
class CustomerLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('customer', 'entry_date', 'entry_type', 'description', 'debit', 'credit')
    search_fields = ('customer__name', 'description')
    list_filter = ('entry_type',)

# Register your models here.
