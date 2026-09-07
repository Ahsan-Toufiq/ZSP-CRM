from decimal import Decimal
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile
from accounts.permissions import AccessLevel, full_tab_permissions
from finance.models import ChequeStatus
from finance.services import create_cheque
from operations.models import Customer


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
