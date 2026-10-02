from django.urls import path
from rest_framework.routers import DefaultRouter

from finance.views import (
    ChequeStatusViewSet,
    ChequeViewSet,
    CurrencyPurchaseViewSet,
    CurrencyCreditorViewSet,
    CurrencyCreditorRepaymentViewSet,
    CurrencyOpeningBalanceViewSet,
    CurrencySpendingViewSet,
    CurrencyViewSet,
    ExpenseViewSet,
    CustomerBalanceViewSet,
    CustomerPaymentViewSet,
    customer_receivable_list,
    customer_statement,
    credit_report,
    daily_payment_report,
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
router.register('currency-creditors', CurrencyCreditorViewSet, basename='currency-creditor')
router.register('currency-creditor-repayments', CurrencyCreditorRepaymentViewSet, basename='currency-creditor-repayment')
router.register('currency-opening-balances', CurrencyOpeningBalanceViewSet, basename='currency-opening-balance')
router.register('currency-spending', CurrencySpendingViewSet, basename='currency-spending')
router.register('expenses', ExpenseViewSet, basename='expense')

urlpatterns = [
    path('dashboard-summary/', dashboard_summary, name='dashboard-summary'),
    path('credit-report/', credit_report, name='credit-report'),
    path('daily-payments/', daily_payment_report, name='daily-payment-report'),
    path('customers/<uuid:customer_id>/receivables/', customer_receivable_list, name='customer-receivables'),
    path('customers/<uuid:customer_id>/statement/', customer_statement, name='customer-statement'),
    *router.urls,
]
