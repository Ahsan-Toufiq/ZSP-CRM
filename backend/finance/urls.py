from django.urls import path
from rest_framework.routers import DefaultRouter

from finance.views import (
    ChequeStatusViewSet,
    ChequeViewSet,
    CustomerBalanceViewSet,
    credit_report,
    LedgerEntryViewSet,
    dashboard_summary,
)

router = DefaultRouter()
router.register('cheque-statuses', ChequeStatusViewSet, basename='cheque-status')
router.register('cheques', ChequeViewSet, basename='cheque')
router.register('ledger', LedgerEntryViewSet, basename='ledger')
router.register('customer-balances', CustomerBalanceViewSet, basename='customer-balance')

urlpatterns = [
    path('dashboard-summary/', dashboard_summary, name='dashboard-summary'),
    path('credit-report/', credit_report, name='credit-report'),
    *router.urls,
]
