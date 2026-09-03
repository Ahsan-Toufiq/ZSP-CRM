from django.contrib import admin

from audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'entity_type', 'entity_id', 'message')
    search_fields = ('action', 'entity_type', 'entity_id', 'message')
    list_filter = ('action', 'entity_type')
    readonly_fields = ('created_at', 'updated_at')

# Register your models here.
