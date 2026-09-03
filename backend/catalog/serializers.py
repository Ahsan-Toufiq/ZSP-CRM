from rest_framework import serializers

from catalog.models import DropdownOption


class DropdownOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = DropdownOption
        fields = ['id', 'group', 'label', 'value', 'is_system', 'is_active', 'sort_order']
        read_only_fields = ['id', 'value', 'is_system']
