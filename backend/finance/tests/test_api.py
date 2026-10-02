from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, full_tab_permissions
from finance.models import (
    ChequeStatus,
    Currency,
    CurrencyCreditor,
    CurrencyCreditorRepayment,
    CurrencyOpeningBalance,
    CurrencyPurchase,
    CurrencySpending,
    Expense,
    CustomerLedgerEntry,
    CustomerPayment,
    CustomerPaymentComponent,
    CustomerPaymentAllocation,
    CustomerPaymentTarget,
)
from finance.services import change_cheque_status, create_cheque
from operations.models import AuctionSale, Customer, InventoryBatch, PartInventory
from operations.services import create_auction_sale


@pytest.fixture
def admin_user(db):
    user = User.objects.create_user(username='finance-api', password='StrongPass123!')
    UserProfile.objects.create(user=user, tab_permissions=full_tab_permissions())
    return user


@pytest.fixture
def api_client(admin_user):
    client = APIClient()
    client.login(username=admin_user.username, password='StrongPass123!')
    return client


@pytest.mark.django_db
def test_credit_report_exports_json_csv_and_pdf(api_client):
    json_response = api_client.get('/api/finance/credit-report/')
    csv_response = api_client.get('/api/finance/credit-report/?export=csv')
    pdf_response = api_client.get('/api/finance/credit-report/?export=pdf')

    assert json_response.status_code == 200
    assert 'generated_at' in json_response.data
    assert csv_response.status_code == 200
    assert csv_response['Content-Type'].startswith('text/csv')
    assert b'ZSP Customer Credit And Aging Report' in csv_response.content
    assert pdf_response.status_code == 200
    assert pdf_response['Content-Type'] == 'application/pdf'
    assert pdf_response.content.startswith(b'%PDF')


@pytest.mark.django_db
@pytest.mark.parametrize('section', ['summary', 'aging', 'outstanding', 'combined'])
def test_credit_report_exports_each_requested_section(api_client, section):
    csv_response = api_client.get(f'/api/finance/credit-report/?export=csv&section={section}')
    pdf_response = api_client.get(f'/api/finance/credit-report/?export=pdf&section={section}')
    assert csv_response.status_code == 200
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b'%PDF')


@pytest.mark.django_db
@pytest.mark.parametrize('report_type', ['aging', 'transactions', 'outstanding', 'combined'])
def test_individual_customer_report_types(api_client, report_type):
    customer = Customer.objects.create(name='Report Customer', phone='+923001234567')
    response = api_client.get(f'/api/finance/customers/{customer.id}/statement/?report={report_type}')
    assert response.status_code == 200
    assert response.content.startswith(b'%PDF')


@pytest.mark.django_db
def test_combined_customer_report_handles_maximum_length_payment_reference(api_client):
    customer = Customer.objects.create(name='Long Reference Customer', phone='+923001234567')
    payment = CustomerPayment.objects.create(
        payment_number='PAY-LONG-REFERENCE',
        customer=customer,
        payment_date=timezone.localdate(),
        kind=CustomerPayment.PaymentKind.BANK_TRANSFER,
        total_amount=Decimal('1000.00'),
    )
    CustomerPaymentComponent.objects.create(
        payment=payment,
        method=CustomerPaymentComponent.Method.BANK_TRANSFER,
        amount=Decimal('1000.00'),
        reference='R' * 120,
    )

    response = api_client.get(f'/api/finance/customers/{customer.id}/statement/?report=combined')

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF')


@pytest.mark.django_db
def test_credit_currency_purchase_and_partial_repayments(api_client):
    currency = Currency.objects.get(code='USD')
    purchase_response = api_client.post(
        '/api/finance/currency-purchases/',
        {
            'currency': str(currency.id),
            'purchase_type': 'credit',
            'creditor_input': 'Tokyo Test Creditor',
            'purchase_date': str(timezone.localdate()),
            'due_date': str(timezone.localdate() + timedelta(days=30)),
            'amount': '1000.0000',
        },
        format='json',
    )
    assert purchase_response.status_code == 201
    purchase = CurrencyPurchase.objects.get(pk=purchase_response.data['id'])
    assert purchase.creditor.name == 'Tokyo Test Creditor'
    assert purchase.acquisition_rate is None
    assert purchase.total_cost is None

    first = api_client.post(
        '/api/finance/currency-creditor-repayments/',
        {
            'purchase': str(purchase.id),
            'repayment_date': str(timezone.localdate()),
            'amount': '300.0000',
            'exchange_rate': '280.000000',
        },
        format='json',
    )
    second = api_client.post(
        '/api/finance/currency-creditor-repayments/',
        {
            'purchase': str(purchase.id),
            'repayment_date': str(timezone.localdate()),
            'amount': '200.0000',
            'total_cost': '57000.00',
        },
        format='json',
    )
    overpayment = api_client.post(
        '/api/finance/currency-creditor-repayments/',
        {
            'purchase': str(purchase.id),
            'repayment_date': str(timezone.localdate()),
            'amount': '501.0000',
            'exchange_rate': '281.000000',
        },
        format='json',
    )
    assert first.status_code == 201
    assert first.data['total_cost'] == '84000.00'
    assert second.status_code == 201
    assert second.data['exchange_rate'] == '285.000000'
    assert overpayment.status_code == 400
    assert CurrencyCreditorRepayment.objects.filter(purchase=purchase).count() == 2
    creditor_response = api_client.get('/api/finance/currency-creditors/')
    creditor = next(item for item in creditor_response.data['results'] if item['name'] == 'Tokyo Test Creditor')
    assert creditor['outstanding_by_currency'] == [{'currency_code': 'USD', 'amount': Decimal('500.0000')}]


@pytest.mark.django_db
def test_dashboard_summary_includes_pending_in_date_cheques(api_client, admin_user):
    customer = Customer.objects.create(name='Cheque Ready Customer', phone='+923009998888')
    create_cheque(
        user=admin_user,
        cheque_number='CHQ-READY-API',
        customer=customer,
        name_on_cheque='Cheque Ready Customer',
        bank_name='HBL',
        amount=Decimal('12000.00'),
        cheque_date=timezone.localdate(),
        expiry_date=timezone.localdate() + timedelta(days=10),
        status=ChequeStatus.objects.get(name='Pending'),
    )

    response = api_client.get('/api/finance/dashboard-summary/')

    assert response.status_code == 200
    assert any(cheque['cheque_number'] == 'CHQ-READY-API' for cheque in response.data['pending_in_date_cheques'])
    assert response.data['cheques_by_status']['Pending'] >= 1


@pytest.mark.django_db
def test_credit_report_requires_customer_tab_access(db):
    user = User.objects.create_user(username='sales-only-api', password='StrongPass123!')
    UserProfile.objects.create(user=user, tab_permissions={'sales': AccessLevel.FULL})
    client = APIClient()
    client.login(username=user.username, password='StrongPass123!')

    response = client.get('/api/finance/credit-report/')

    assert response.status_code == 403


@pytest.mark.django_db
def test_customer_cash_payment_posts_ledger_and_allocates_oldest_sale(api_client, admin_user):
    customer = Customer.objects.create(name='Payment Customer', phone='+923001112222')
    item = PartInventory.objects.create(part_name='Gearbox', quantity=1, unit='piece')
    batch = InventoryBatch.objects.create(item=item, quantity=1, raw_unit_cost=Decimal('1000.00'), source_label='Test')
    sale = create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate() - timedelta(days=3),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('15000.00')}],
    )

    response = api_client.post(
        '/api/finance/customer-payments/',
        {
            'customer': str(customer.id),
            'payment_date': str(timezone.localdate()),
            'components': [{'method': 'cash', 'amount': '5000.00'}],
        },
        format='json',
    )

    assert response.status_code == 201
    payment = CustomerPayment.objects.get(customer=customer)
    ledger = CustomerLedgerEntry.objects.get(payment=payment)
    assert ledger.credit == Decimal('5000.00')
    allocation = CustomerPaymentAllocation.objects.get(sale=sale)
    assert allocation.amount == Decimal('5000.00')


@pytest.mark.django_db
def test_customer_cheque_payment_creates_pending_cheque_without_ledger_credit(api_client):
    customer = Customer.objects.create(name='Cheque Payment Customer', phone='+923001113333')
    pending = ChequeStatus.objects.get(name='Pending')
    CustomerLedgerEntry.objects.create(
        customer=customer,
        entry_date=timezone.localdate(),
        entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
        description='Opening balance',
        debit=Decimal('7000.00'),
    )

    response = api_client.post(
        '/api/finance/customer-payments/',
        {
            'customer': str(customer.id),
            'payment_date': str(timezone.localdate()),
            'components': [
                {
                    'method': 'cheque',
                    'amount': '7000.00',
                    'cheque': {
                        'cheque_number': 'PAY-CHQ-1',
                        'name_on_cheque': 'Cheque Payment Customer',
                        'bank_name': 'HBL',
                        'cheque_date': str(timezone.localdate()),
                        'expiry_date': str(timezone.localdate() + timedelta(days=30)),
                    },
                },
            ],
        },
        format='json',
    )

    assert response.status_code == 201
    payment = CustomerPayment.objects.get(customer=customer)
    component = payment.components.get()
    assert component.cheque.status == pending
    assert not CustomerLedgerEntry.objects.filter(payment=payment).exists()


@pytest.mark.django_db
def test_specific_payment_allocates_to_sale_and_opening_balance(api_client, admin_user):
    customer = Customer.objects.create(name='Allocated Customer', phone='+923001119001')
    opening = CustomerLedgerEntry.objects.create(
        customer=customer,
        entry_date=timezone.localdate() - timedelta(days=10),
        entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
        description='Opening balance',
        debit=Decimal('5000.00'),
    )
    item = PartInventory.objects.create(part_name='Allocated gearbox', quantity=1, unit='piece')
    batch = InventoryBatch.objects.create(item=item, quantity=1, raw_unit_cost=Decimal('1000.00'), source_label='Test')
    sale = create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate() - timedelta(days=2),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': batch, 'quantity': 1, 'sold_price': Decimal('10000.00')}],
    )

    response = api_client.post('/api/finance/customer-payments/', {
        'customer': str(customer.id),
        'payment_date': str(timezone.localdate()),
        'allocation_mode': 'specific',
        'targets': [
            {'target_type': 'opening_balance', 'target_id': str(opening.id), 'amount': '2000.00'},
            {'target_type': 'sale', 'target_id': str(sale.id), 'amount': '3000.00'},
        ],
        'components': [{'method': 'cash', 'amount': '5000.00'}],
    }, format='json')

    assert response.status_code == 201
    payment = CustomerPayment.objects.get(customer=customer)
    assert payment.allocation_mode == CustomerPayment.AllocationMode.SPECIFIC
    assert CustomerPaymentTarget.objects.filter(payment=payment).count() == 2
    allocations = payment.components.get().allocations.all()
    assert sum(allocation.amount for allocation in allocations) == Decimal('5000.00')
    assert allocations.filter(opening_balance=opening, amount=Decimal('2000.00')).exists()
    assert allocations.filter(sale=sale, amount=Decimal('3000.00')).exists()


@pytest.mark.django_db
def test_specific_payment_rejects_amount_above_selected_receivable(api_client):
    customer = Customer.objects.create(name='Bounded Customer', phone='+923001119002')
    opening = CustomerLedgerEntry.objects.create(
        customer=customer,
        entry_date=timezone.localdate(),
        entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
        description='Opening balance',
        debit=Decimal('1000.00'),
    )

    response = api_client.post('/api/finance/customer-payments/', {
        'customer': str(customer.id),
        'payment_date': str(timezone.localdate()),
        'allocation_mode': 'specific',
        'targets': [{'target_type': 'opening_balance', 'target_id': str(opening.id), 'amount': '1200.00'}],
        'components': [{'method': 'cash', 'amount': '1200.00'}],
    }, format='json')

    assert response.status_code == 400
    assert 'cannot exceed' in str(response.data).lower()
    assert not CustomerPayment.objects.filter(customer=customer).exists()


@pytest.mark.django_db
def test_specific_pending_cheque_honors_selected_sale_when_cleared(api_client, admin_user):
    customer = Customer.objects.create(name='Targeted Cheque Customer', phone='+923001119003')
    first_item = PartInventory.objects.create(part_name='Older receivable', quantity=1, unit='piece')
    second_item = PartInventory.objects.create(part_name='Selected receivable', quantity=1, unit='piece')
    first_sale = create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate() - timedelta(days=20),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': InventoryBatch.objects.create(item=first_item, quantity=1), 'sold_price': Decimal('5000.00')}],
    )
    second_sale = create_auction_sale(
        user=admin_user,
        sale_date=timezone.localdate() - timedelta(days=2),
        payment_type=AuctionSale.PaymentType.CREDIT,
        customer=customer,
        lines=[{'inventory_batch': InventoryBatch.objects.create(item=second_item, quantity=1), 'sold_price': Decimal('7000.00')}],
    )
    response = api_client.post('/api/finance/customer-payments/', {
        'customer': str(customer.id),
        'payment_date': str(timezone.localdate()),
        'allocation_mode': 'specific',
        'targets': [{'target_type': 'sale', 'target_id': str(second_sale.id), 'amount': '4000.00'}],
        'components': [{'method': 'cheque', 'amount': '4000.00', 'cheque': {
            'cheque_number': 'TARGET-CHQ-1',
            'bank_name': 'HBL',
            'cheque_date': str(timezone.localdate()),
            'expiry_date': str(timezone.localdate() + timedelta(days=30)),
        }}],
    }, format='json')
    assert response.status_code == 201

    payment = CustomerPayment.objects.get(customer=customer)
    cheque = payment.components.get().cheque
    change_cheque_status(user=admin_user, cheque=cheque, status=ChequeStatus.objects.get(name='Cleared'))

    allocation = cheque.settlement_allocations.get(is_reversed=False)
    assert allocation.sale == second_sale
    assert allocation.amount == Decimal('4000.00')
    assert not cheque.settlement_allocations.filter(sale=first_sale).exists()


@pytest.mark.django_db
def test_customer_receivables_and_daily_payment_reports(api_client):
    customer = Customer.objects.create(name='Daily Report Customer', phone='+923001119004')
    CustomerLedgerEntry.objects.create(
        customer=customer,
        entry_date=timezone.localdate(),
        entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
        description='Opening balance',
        debit=Decimal('3000.00'),
    )
    receivables = api_client.get(f'/api/finance/customers/{customer.id}/receivables/')
    payment = api_client.post('/api/finance/customer-payments/', {
        'customer': str(customer.id),
        'payment_date': str(timezone.localdate()),
        'allocation_mode': 'overall',
        'components': [{'method': 'cash', 'amount': '1000.00'}],
    }, format='json')
    report = api_client.get(f'/api/finance/daily-payments/?date={timezone.localdate()}')
    pdf = api_client.get(f'/api/finance/daily-payments/?date={timezone.localdate()}&export=pdf')

    assert receivables.status_code == 200
    assert receivables.data['results'][0]['reference'] == 'Opening balance'
    assert payment.status_code == 201
    assert report.status_code == 200
    assert report.data['totals']['payment_count'] == 1
    assert Decimal(report.data['rows'][0]['balance_after']) == Decimal('2000.00')
    assert pdf.status_code == 200
    assert pdf.content.startswith(b'%PDF')


@pytest.mark.django_db
def test_customer_write_off_requires_an_explicit_reason(api_client):
    customer = Customer.objects.create(name='Adjustment Customer', phone='+923001113334')

    response = api_client.post(
        '/api/finance/customer-payments/',
        {
            'customer': str(customer.id),
            'payment_date': str(timezone.localdate()),
            'components': [{'method': 'write_off', 'amount': '500.00', 'notes': ''}],
        },
        format='json',
    )

    assert response.status_code == 400
    assert 'notes' in response.data['components'][0]
    assert not CustomerPayment.objects.filter(customer=customer).exists()


@pytest.mark.django_db
def test_customer_statement_pdf_exports_customer_history(api_client):
    customer = Customer.objects.create(name='Statement Customer', phone='+923001114444')
    CustomerLedgerEntry.objects.create(
        customer=customer,
        entry_date=timezone.localdate(),
        entry_type=CustomerLedgerEntry.EntryType.ADJUSTMENT,
        description='Opening balance',
        debit=Decimal('1000.00'),
    )

    response = api_client.get(f'/api/finance/customers/{customer.id}/statement/')

    assert response.status_code == 200
    assert response['Content-Type'] == 'application/pdf'
    assert response.content.startswith(b'%PDF')


@pytest.mark.django_db
def test_currency_purchase_calculates_missing_total_and_rate(api_client):
    currency = Currency.objects.get(code='USD')

    total_response = api_client.post(
        '/api/finance/currency-purchases/',
        {
            'currency': str(currency.id),
            'purchase_date': str(timezone.localdate()),
            'amount': '100.0000',
            'acquisition_rate': '280.500000',
            'source': 'Money exchanger',
        },
        format='json',
    )
    rate_response = api_client.post(
        '/api/finance/currency-purchases/',
        {
            'currency': str(currency.id),
            'purchase_date': str(timezone.localdate()),
            'amount': '50.0000',
            'total_cost': '15000.00',
        },
        format='json',
    )

    assert total_response.status_code == 201
    assert total_response.data['total_cost'] == '28050.00'
    assert rate_response.status_code == 201
    assert rate_response.data['acquisition_rate'] == '300.000000'


@pytest.mark.django_db
def test_currency_purchase_accepts_optional_context_and_creates_custom_currency(api_client):
    response = api_client.post(
        '/api/finance/currency-purchases/',
        {
            'currency_input': 'AED - UAE Dirham',
            'purchase_date': str(timezone.localdate()),
            'amount': '25.0000',
            'total_cost': '1900.00',
        },
        format='json',
    )

    assert response.status_code == 201
    assert response.data['currency_code'] == 'AED'
    assert response.data['source'] == ''
    assert response.data['reference'] == ''
    assert response.data['notes'] == ''
    assert Currency.objects.filter(code='AED', name='UAE Dirham').exists()


@pytest.mark.django_db
def test_currency_opening_balance_allows_unknown_cost_and_remains_visible_at_zero(api_client):
    opening_response = api_client.post(
        '/api/finance/currency-opening-balances/',
        {
            'currency_input': 'SAR - Saudi Riyal',
            'entry_date': str(timezone.localdate()),
            'amount': '100.0000',
        },
        format='json',
    )
    currency = Currency.objects.get(code='SAR')
    spending_response = api_client.post(
        '/api/finance/currency-spending/',
        {
            'currency': str(currency.id),
            'spending_date': str(timezone.localdate()),
            'amount': '100.0000',
        },
        format='json',
    )
    summary_response = api_client.get(f'/api/finance/currencies/{currency.id}/')

    assert opening_response.status_code == 201
    assert opening_response.data['acquisition_rate'] is None
    assert opening_response.data['total_cost'] is None
    assert spending_response.status_code == 201
    assert summary_response.status_code == 200
    assert summary_response.data['current_amount'] == Decimal('0.0000')
    assert summary_response.data['has_activity'] is True


@pytest.mark.django_db
def test_currency_allows_only_one_opening_balance(api_client):
    currency = Currency.objects.get(code='JPY')
    first = api_client.post(
        '/api/finance/currency-opening-balances/',
        {
            'currency': str(currency.id),
            'entry_date': str(timezone.localdate()),
            'amount': '1000.0000',
        },
        format='json',
    )
    duplicate = api_client.post(
        '/api/finance/currency-opening-balances/',
        {
            'currency_input': 'JPY - Japanese Yen',
            'entry_date': str(timezone.localdate()),
            'amount': '500.0000',
        },
        format='json',
    )

    assert first.status_code == 201
    assert duplicate.status_code == 400
    assert duplicate.data['currency_input'][0] == 'JPY already has an opening balance. Edit the existing entry instead.'
    assert CurrencyOpeningBalance.objects.filter(currency=currency).count() == 1
    assert CurrencyOpeningBalance.objects.get(currency=currency).amount == Decimal('1000.0000')


@pytest.mark.django_db
def test_currency_spending_reduces_balance_and_rejects_overspending(api_client):
    currency = Currency.objects.get(code='USD')
    CurrencyOpeningBalance.objects.create(
        currency=currency,
        entry_date=timezone.localdate(),
        amount=Decimal('50.0000'),
    )

    accepted = api_client.post(
        '/api/finance/currency-spending/',
        {
            'currency': str(currency.id),
            'spending_date': str(timezone.localdate()),
            'amount': '20.0000',
            'purpose': 'Supplier settlement',
        },
        format='json',
    )
    rejected = api_client.post(
        '/api/finance/currency-spending/',
        {
            'currency': str(currency.id),
            'spending_date': str(timezone.localdate()),
            'amount': '31.0000',
        },
        format='json',
    )

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert 'amount' in rejected.data
    assert CurrencySpending.objects.filter(currency=currency).count() == 1


@pytest.mark.django_db
def test_acquisition_cannot_be_reduced_or_deleted_below_recorded_spending(api_client):
    currency = Currency.objects.get(code='USD')
    opening = CurrencyOpeningBalance.objects.create(
        currency=currency,
        entry_date=timezone.localdate(),
        amount=Decimal('50.0000'),
    )
    CurrencySpending.objects.create(
        currency=currency,
        spending_date=timezone.localdate(),
        amount=Decimal('20.0000'),
    )

    reduction = api_client.patch(
        f'/api/finance/currency-opening-balances/{opening.id}/',
        {'amount': '10.0000'},
        format='json',
    )
    deletion = api_client.delete(f'/api/finance/currency-opening-balances/{opening.id}/')

    assert reduction.status_code == 400
    assert 'amount' in reduction.data
    assert deletion.status_code == 400
    assert CurrencyOpeningBalance.objects.filter(pk=opening.id).exists()


@pytest.mark.django_db
def test_expense_crud_persists_reusable_dropdown_values(api_client):
    response = api_client.post(
        '/api/finance/expenses/',
        {
            'expense_date': str(timezone.localdate()),
            'title': 'Workshop maintenance',
            'category': 'Repairs',
            'amount': '12500.00',
            'payee': 'Local mechanic',
            'payment_method': 'Cash',
            'reference': 'EXP-TEST-001',
        },
        format='json',
    )

    assert response.status_code == 201
    assert Expense.objects.get(pk=response.data['id']).amount == Decimal('12500.00')
    expected_options = {
        ('expense_title', 'Workshop maintenance'),
        ('expense_category', 'Repairs'),
        ('expense_payee', 'Local mechanic'),
        ('expense_payment_method', 'Cash'),
    }
    from catalog.models import DropdownOption
    assert expected_options.issubset(set(DropdownOption.objects.values_list('group', 'label')))

    invalid = api_client.post(
        '/api/finance/expenses/',
        {'expense_date': str(timezone.localdate()), 'title': 'Invalid', 'category': 'Test', 'amount': '0.00'},
        format='json',
    )
    assert invalid.status_code == 400
    assert 'amount' in invalid.data


@pytest.mark.django_db
@pytest.mark.parametrize('granularity', ['day', 'week', 'month', 'year'])
def test_expense_analytics_supports_all_time_groupings(api_client, granularity):
    today = timezone.localdate()
    Expense.objects.create(expense_date=today - timedelta(days=8), title='Rent', category='Premises', amount=Decimal('1000.00'))
    Expense.objects.create(expense_date=today, title='Labour', category='Operations', amount=Decimal('2500.00'))

    response = api_client.get(
        f'/api/finance/expenses/analytics/?start={today - timedelta(days=30)}&end={today}&granularity={granularity}'
    )

    assert response.status_code == 200
    assert response.data['totals']['total'] == Decimal('3500.00')
    assert response.data['totals']['count'] == 2
    assert response.data['date_bounds']['granularity'] == granularity
    assert response.data['selected']
