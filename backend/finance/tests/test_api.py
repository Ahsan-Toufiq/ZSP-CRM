from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, full_tab_permissions
from finance.models import ChequeStatus, Currency, CustomerLedgerEntry, CustomerPayment, CustomerPaymentAllocation
from finance.services import create_cheque
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
    assert b'ZSP Credit, Aging, And Customer Balance Report' in csv_response.content
    assert pdf_response.status_code == 200
    assert pdf_response['Content-Type'] == 'application/pdf'
    assert pdf_response.content.startswith(b'%PDF')


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
