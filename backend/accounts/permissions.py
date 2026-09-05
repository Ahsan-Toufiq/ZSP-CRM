from rest_framework.permissions import BasePermission, SAFE_METHODS


class Roles:
    ADMIN = 'Admin'
    OPERATIONS = 'Operations'
    FINANCE = 'Finance'
    GATEKEEPER = 'Gatekeeper'


class AccessLevel:
    NONE = 'none'
    VIEW = 'view'
    FULL = 'full'


ALL_TABS = {'dashboard', 'customers', 'containers', 'sales', 'cheques', 'settings', 'users'}
PERMANENT_ADMIN_USERNAME = 'admin'

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


def full_tab_permissions() -> dict[str, str]:
    return {tab: AccessLevel.FULL for tab in sorted(ALL_TABS)}


def tab_permissions_for_user(user) -> dict[str, str]:
    if not user or not user.is_authenticated:
        return {}
    if user.is_superuser or user.username == PERMANENT_ADMIN_USERNAME:
        return full_tab_permissions()
    if hasattr(user, 'profile') and user.profile.tab_permissions:
        return {
            tab: level
            for tab, level in user.profile.tab_permissions.items()
            if tab in ALL_TABS and level in {AccessLevel.VIEW, AccessLevel.FULL}
        }
    if hasattr(user, 'profile'):
        return {tab: AccessLevel.FULL for tab in user.profile.allowed_tabs if tab in ALL_TABS}
    return {}


def allowed_tabs_for_user(user) -> list[str]:
    permissions = tab_permissions_for_user(user)
    return sorted(tab for tab, level in permissions.items() if level in {AccessLevel.VIEW, AccessLevel.FULL})


def has_tab_access(user, tab: str, *, write: bool = False) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.username == PERMANENT_ADMIN_USERNAME:
        return True
    level = tab_permissions_for_user(user).get(tab, AccessLevel.NONE)
    return level == AccessLevel.FULL if write else level in {AccessLevel.VIEW, AccessLevel.FULL}


def has_view_permission(user, view, request) -> bool:
    tab = VIEW_TAB_MAP.get(view.__class__.__name__)
    if tab is None:
        return True
    return has_tab_access(user, tab, write=request.method not in SAFE_METHODS)


class OperationsPermission(BasePermission):
    def has_permission(self, request, view):
        return has_view_permission(request.user, view, request)


class FinancePermission(BasePermission):
    def has_permission(self, request, view):
        view_name = view.__class__.__name__
        if view_name == 'ChequeStatusViewSet':
            if request.method in SAFE_METHODS:
                return has_tab_access(request.user, 'cheques') or has_tab_access(request.user, 'settings')
            return has_tab_access(request.user, 'settings', write=True)
        return has_view_permission(request.user, view, request)


class DashboardPermission(BasePermission):
    def has_permission(self, request, view):
        return has_tab_access(request.user, 'dashboard')


class AdminPermission(BasePermission):
    def has_permission(self, request, view):
        return has_tab_access(request.user, 'users', write=request.method not in SAFE_METHODS)
