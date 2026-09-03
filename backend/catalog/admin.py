from django.contrib import admin

from catalog.models import DropdownOption


@admin.register(DropdownOption)
class DropdownOptionAdmin(admin.ModelAdmin):
    list_display = ('group', 'label', 'is_system', 'is_active', 'sort_order')
    list_filter = ('group', 'is_system', 'is_active')
    search_fields = ('label', 'value')
