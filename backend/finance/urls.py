from django.urls import path
from rest_framework.routers import DefaultRouter

from finance.views import (
    ChequeStatusViewSet,
    ChequeViewSet,
    CurrencyPurchaseViewSet,
    CurrencyViewSet,
    CustomerBalanceViewSet,
    CustomerPaymentViewSet,
    customer_statement,
    credit_report,
    LedgerEntryViewSet,
    dashboard_summary,
)

router = DefaultRouter()
router.register('cheque-statuses', ChequeStatusViewSet, basename='cheque-status')
router.register('cheques', ChequeViewSet, basename='cheque')
router.register('customer-payments', CustomerPaymentViewSet, basename='customer-payment')
router.register('ledger', LedgerEntryViewSet, basename='ledger')
router.register('customer-balances', CustomerBalanceViewSet, basename='customer-balance')
router.register('currencies', CurrencyViewSet, basename='currency')
router.register('currency-purchases', CurrencyPurchaseViewSet, basename='currency-purchase')

urlpatterns = [
    path('dashboard-summary/', dashboard_summary, name='dashboard-summary'),
    path('credit-report/', credit_report, name='credit-report'),
    path('customers/<uuid:customer_id>/statement/', customer_statement, name='customer-statement'),
    *router.urls,
]
