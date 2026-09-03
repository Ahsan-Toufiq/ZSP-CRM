from rest_framework import viewsets
from rest_framework.permissions import BasePermission

from accounts.permissions import has_role, Roles
from catalog.models import DropdownOption
from catalog.serializers import DropdownOptionSerializer


class DropdownOptionPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in {'GET', 'HEAD', 'OPTIONS'}:
            return request.user and request.user.is_authenticated
        return has_role(request.user, Roles.ADMIN, Roles.OPERATIONS, Roles.FINANCE)


class DropdownOptionViewSet(viewsets.ModelViewSet):
    queryset = DropdownOption.objects.all()
    serializer_class = DropdownOptionSerializer
    permission_classes = [DropdownOptionPermission]
    filterset_fields = ['group', 'is_active']
    search_fields = ['label']
    ordering_fields = ['group', 'sort_order', 'label']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
