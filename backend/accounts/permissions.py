from rest_framework.permissions import BasePermission


class Roles:
    ADMIN = 'Admin'
    OPERATIONS = 'Operations'
    FINANCE = 'Finance'
    GATEKEEPER = 'Gatekeeper'


ROLE_DEFAULT_TABS = {
    Roles.ADMIN: {'dashboard', 'customers', 'containers', 'sales', 'cheques', 'settings', 'users'},
    Roles.OPERATIONS: {'dashboard', 'customers', 'containers', 'sales'},
    Roles.FINANCE: {'dashboard', 'customers', 'cheques', 'settings'},
    Roles.GATEKEEPER: {'sales'},
}


ALL_TABS = {'dashboard', 'customers', 'containers', 'sales', 'cheques', 'settings', 'users'}


VIEW_TAB_MAP = {
    'CustomerViewSet': 'customers',
    'ContainerViewSet': 'containers',
    'ContainerItemViewSet': 'containers',
    'PartInventoryViewSet': 'containers',
    'AuctionSaleViewSet': 'sales',
    'GatePassViewSet': 'sales',
    'ChequeViewSet': 'cheques',
    'LedgerEntryViewSet': 'customers',
    'CustomerBalanceViewSet': 'customers',
    'DropdownOptionViewSet': 'settings',
}


def has_role(user, *roles: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def default_tabs_for_user(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(ALL_TABS)
    role_names = set(user.groups.values_list('name', flat=True))
    tabs: set[str] = set()
    for role_name in role_names:
        tabs.update(ROLE_DEFAULT_TABS.get(role_name, set()))
    return tabs


def allowed_tabs_for_user(user) -> list[str]:
    if not user or not user.is_authenticated:
        return []
    if user.is_superuser:
        return sorted(ALL_TABS)
    if hasattr(user, 'profile'):
        return sorted(set(user.profile.allowed_tabs))
    return sorted(default_tabs_for_user(user))


def has_tab_access(user, tab: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return tab in set(allowed_tabs_for_user(user))


def has_view_tab_access(user, view) -> bool:
    tab = VIEW_TAB_MAP.get(view.__class__.__name__)
    return True if tab is None else has_tab_access(user, tab)


class OperationsPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, 'action', None)
        view_name = view.__class__.__name__

        if not has_view_tab_access(request.user, view):
            return False

        if has_role(request.user, Roles.ADMIN, Roles.OPERATIONS):
            return True

        if view_name == 'GatePassViewSet' and action in {'list', 'retrieve'}:
            return has_role(request.user, Roles.GATEKEEPER)

        if view_name == 'AuctionSaleViewSet' and action == 'sold_without_gate_pass':
            return has_role(request.user, Roles.GATEKEEPER)

        if view_name == 'CustomerViewSet' and action in {'list', 'retrieve'}:
            return has_role(request.user, Roles.FINANCE)

        return False


class FinancePermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, 'action', None)
        view_name = view.__class__.__name__

        if view_name == 'ChequeStatusViewSet':
            if request.method in {'GET', 'HEAD', 'OPTIONS'}:
                return (
                    (has_tab_access(request.user, 'cheques') or has_tab_access(request.user, 'settings'))
                    and has_role(request.user, Roles.ADMIN, Roles.FINANCE, Roles.OPERATIONS)
                )
            return has_tab_access(request.user, 'settings') and has_role(request.user, Roles.ADMIN, Roles.FINANCE)

        if not has_view_tab_access(request.user, view):
            return False

        if has_role(request.user, Roles.ADMIN, Roles.FINANCE):
            return True

        if request.method in {'GET', 'HEAD', 'OPTIONS'} and has_role(request.user, Roles.OPERATIONS):
            return True

        return action in {'list', 'retrieve'} and has_role(request.user, Roles.OPERATIONS)


class DashboardPermission(BasePermission):
    def has_permission(self, request, view):
        return has_tab_access(request.user, 'dashboard') and has_role(request.user, Roles.ADMIN, Roles.OPERATIONS, Roles.FINANCE)


class AdminPermission(BasePermission):
    def has_permission(self, request, view):
        return has_role(request.user, Roles.ADMIN) and has_tab_access(request.user, 'users')
