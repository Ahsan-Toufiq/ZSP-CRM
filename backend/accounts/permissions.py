from rest_framework.permissions import BasePermission


class Roles:
    ADMIN = 'Admin'
    OPERATIONS = 'Operations'
    FINANCE = 'Finance'
    GATEKEEPER = 'Gatekeeper'


def has_role(user, *roles: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


class OperationsPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, 'action', None)
        view_name = view.__class__.__name__

        if has_role(request.user, Roles.ADMIN, Roles.OPERATIONS):
            return True

        if view_name == 'GatePassViewSet' and action in {'list', 'retrieve', 'verify'}:
            return has_role(request.user, Roles.GATEKEEPER)

        if view_name == 'AuctionSaleViewSet' and action == 'sold_without_gate_pass':
            return has_role(request.user, Roles.GATEKEEPER)

        if view_name == 'CustomerViewSet' and action in {'list', 'retrieve'}:
            return has_role(request.user, Roles.FINANCE)

        return False


class FinancePermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, 'action', None)

        if has_role(request.user, Roles.ADMIN, Roles.FINANCE):
            return True

        if request.method in {'GET', 'HEAD', 'OPTIONS'} and has_role(request.user, Roles.OPERATIONS):
            return True

        return action in {'list', 'retrieve'} and has_role(request.user, Roles.OPERATIONS)


class DashboardPermission(BasePermission):
    def has_permission(self, request, view):
        return has_role(request.user, Roles.ADMIN, Roles.OPERATIONS, Roles.FINANCE)
