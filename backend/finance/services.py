from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from audit.models import AuditLog
from catalog.models import DropdownOption
from catalog.services import ensure_dropdown_option
from finance.models import (
    Cheque,
    ChequeSettlementAllocation,
    ChequeStatus,
    ChequeStatusHistory,
    Currency,
    CurrencyOpeningBalance,
    CurrencySpending,
    CustomerLedgerEntry,
    CustomerPayment,
    CustomerPaymentAllocation,
    CustomerPaymentComponent,
)
from operations.models import AuctionSale


def resolve_currency(*, currency=None, currency_input='', user=None) -> Currency:
    if currency is not None:
        return currency
    raw_value = str(currency_input or '').strip()
    if not raw_value:
        raise ValidationError({'currency_input': 'Select a currency or enter a new one.'})
    code, separator, supplied_name = raw_value.partition(' - ')
    code = code.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValidationError({'currency_input': 'Use a three-letter currency code, for example USD or USD - US Dollar.'})
    name = supplied_name.strip() if separator and supplied_name.strip() else code
    defaults = {'name': name, 'is_active': True, 'created_by': user, 'updated_by': user}
    currency, _ = Currency.objects.get_or_create(code=code, defaults=defaults)
    if not currency.is_active:
        currency.is_active = True
        currency.updated_by = user
        currency.save(update_fields=['is_active', 'updated_by', 'updated_at'])
    return currency


def currency_balance(currency: Currency, *, exclude_spending_id=None) -> Decimal:
    purchased = currency.purchases.aggregate(total=Sum('amount'))['total'] or Decimal('0.0000')
    opening = currency.opening_balances.aggregate(total=Sum('amount'))['total'] or Decimal('0.0000')
    spending = currency.spending_entries.all()
    if exclude_spending_id:
        spending = spending.exclude(pk=exclude_spending_id)
    spent = spending.aggregate(total=Sum('amount'))['total'] or Decimal('0.0000')
    return purchased + opening - spent


@transaction.atomic
def update_currency_acquisition(*, instance, user, currency, **data):
    currency_ids = sorted({instance.currency_id, currency.id}, key=str)
    locked_currencies = {
        item.id: item for item in Currency.objects.select_for_update().filter(id__in=currency_ids).order_by('id')
    }
    original_currency = locked_currencies[instance.currency_id]
    target_currency = locked_currencies[currency.id]
    new_amount = Decimal(data.get('amount', instance.amount))
    if instance.currency_id == target_currency.id:
        resulting_balance = currency_balance(original_currency) - instance.amount + new_amount
    else:
        resulting_balance = currency_balance(original_currency) - instance.amount
    if resulting_balance < 0:
        raise ValidationError({
            'amount': f'This change would leave {original_currency.code} with a negative balance. Reduce or remove its spending first.',
        })
    instance.currency = target_currency
    instance.updated_by = user
    for field, value in data.items():
        setattr(instance, field, value)
    instance.save()
    return instance


@transaction.atomic
def delete_currency_acquisition(*, instance) -> None:
    locked_currency = Currency.objects.select_for_update().get(pk=instance.currency_id)
    if currency_balance(locked_currency) - instance.amount < 0:
        raise ValidationError({
            'detail': f'This entry cannot be deleted while it supports recorded {locked_currency.code} spending.',
        })
    instance.delete()


@transaction.atomic
def create_currency_spending(*, user, currency, currency_input='', **data) -> CurrencySpending:
    resolved = resolve_currency(currency=currency, currency_input=currency_input, user=user)
    locked = Currency.objects.select_for_update().get(pk=resolved.pk)
    amount = Decimal(data['amount'])
    available = currency_balance(locked)
    if amount > available:
        raise ValidationError({'amount': f'Only {available:.4f} {locked.code} is available.'})
    return CurrencySpending.objects.create(
        currency=locked,
        created_by=user,
        updated_by=user,
        **data,
    )


@transaction.atomic
def update_currency_spending(*, instance, user, currency, currency_input='', **data) -> CurrencySpending:
    resolved = resolve_currency(currency=currency, currency_input=currency_input, user=user)
    currency_ids = sorted({instance.currency_id, resolved.id}, key=str)
    locked_currencies = {
        item.id: item for item in Currency.objects.select_for_update().filter(id__in=currency_ids).order_by('id')
    }
    target = locked_currencies[resolved.id]
    amount = Decimal(data.get('amount', instance.amount))
    exclude_id = instance.id if instance.currency_id == target.id else None
    available = currency_balance(target, exclude_spending_id=exclude_id)
    if amount > available:
        raise ValidationError({'amount': f'Only {available:.4f} {target.code} is available.'})
    instance.currency = target
    instance.updated_by = user
    for field, value in data.items():
        setattr(instance, field, value)
    instance.save()
    return instance


@transaction.atomic
def create_cheque(*, user, **data) -> Cheque:
    ensure_dropdown_option(group=DropdownOption.Group.BANK, label=data.get('bank_name', ''), user=user)
    requested_status = data.pop('status')
    initial_status = requested_status
    if requested_status.balance_effect != ChequeStatus.BalanceEffect.NONE:
        initial_status = (
            ChequeStatus.objects
            .filter(name='Pending', balance_effect=ChequeStatus.BalanceEffect.NONE, is_active=True)
            .first()
            or requested_status
        )
    cheque = Cheque.objects.create(created_by=user, updated_by=user, status=initial_status, **data)
    ChequeStatusHistory.objects.create(
        cheque=cheque,
        from_status=None,
        to_status=cheque.status,
        notes='Cheque created',
        created_by=user,
        updated_by=user,
    )
    AuditLog.objects.create(
        actor=user,
        action='cheque.created',
        entity_type='Cheque',
        entity_id=str(cheque.id),
        message=f'Created cheque {cheque.cheque_number}',
        metadata={'amount': str(cheque.amount), 'status': cheque.status.name},
    )
    if requested_status.id != initial_status.id:
        cheque = change_cheque_status(user=user, cheque=cheque, status=requested_status, notes='Initial cheque status')
    return cheque


def _active_allocated_amount(sale: AuctionSale) -> Decimal:
    return sale.cheque_allocations.filter(is_reversed=False).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def _active_direct_payment_amount(sale: AuctionSale) -> Decimal:
    return sale.payment_allocations.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')


def _sale_outstanding(sale: AuctionSale) -> Decimal:
    return Decimal(sale.receivable_amount) - _active_allocated_amount(sale) - _active_direct_payment_amount(sale)


def _allocate_cheque_to_oldest_sales(*, user, cheque: Cheque) -> None:
    remaining = Decimal(cheque.amount)
    sales = (
        AuctionSale.objects
        .select_for_update()
        .filter(
            customer=cheque.customer,
            payment_type__in=[
                AuctionSale.PaymentType.CREDIT,
                AuctionSale.PaymentType.CHEQUE,
                AuctionSale.PaymentType.MIXED,
            ],
            is_cancelled=False,
        )
        .order_by('sale_date', 'created_at')
    )

    for sale in sales:
        if remaining <= 0:
            break
        outstanding = _sale_outstanding(sale)
        if outstanding <= 0:
            continue
        amount = min(remaining, outstanding)
        ChequeSettlementAllocation.objects.create(
            cheque=cheque,
            sale=sale,
            amount=amount,
            created_by=user,
            updated_by=user,
        )
        remaining -= amount


def _allocate_component_to_oldest_sales(*, user, component: CustomerPaymentComponent) -> None:
    remaining = Decimal(component.amount)
    sales = (
        AuctionSale.objects
        .select_for_update()
        .filter(
            customer=component.payment.customer,
            payment_type__in=[
                AuctionSale.PaymentType.CREDIT,
                AuctionSale.PaymentType.CHEQUE,
                AuctionSale.PaymentType.MIXED,
            ],
            is_cancelled=False,
        )
        .order_by('sale_date', 'created_at')
    )
    for sale in sales:
        if remaining <= 0:
            break
        outstanding = _sale_outstanding(sale)
        if outstanding <= 0:
            continue
        amount = min(remaining, outstanding)
        CustomerPaymentAllocation.objects.create(
            component=component,
            sale=sale,
            amount=amount,
            created_by=user,
            updated_by=user,
        )
        remaining -= amount


def _post_cheque_settlement(*, user, cheque: Cheque) -> None:
    existing_settlement = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists()
    active_allocations = cheque.settlement_allocations.filter(is_reversed=False).exists()
    if existing_settlement:
        if active_allocations:
            return
        allocated_once = cheque.settlement_allocations.exists()
        if allocated_once:
            return
    CustomerLedgerEntry.objects.create(
        customer=cheque.customer,
        entry_date=cheque.received_date or timezone.localdate(),
        entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT,
        description=f'Cheque settlement {cheque.cheque_number}',
        credit=cheque.amount,
        cheque=cheque,
        created_by=user,
        updated_by=user,
    )
    _allocate_cheque_to_oldest_sales(user=user, cheque=cheque)


def next_customer_payment_number() -> str:
    prefix = timezone.localdate().strftime('PAY-%Y%m%d')
    count = CustomerPayment.objects.filter(payment_number__startswith=prefix).count() + 1
    return f'{prefix}-{count:04d}'


def _payment_kind_for_components(components: list[dict]) -> str:
    methods = {component['method'] for component in components}
    if len(methods) == 1:
        method = next(iter(methods))
        if method == CustomerPaymentComponent.Method.BANK_TRANSFER:
            return CustomerPayment.PaymentKind.BANK_TRANSFER
        if method == CustomerPaymentComponent.Method.WRITE_OFF:
            return CustomerPayment.PaymentKind.WRITE_OFF
        return method
    return CustomerPayment.PaymentKind.SPLIT


def _create_component_cheque(*, user, payment: CustomerPayment, component: CustomerPaymentComponent, cheque_data: dict) -> Cheque:
    pending_status = (
        ChequeStatus.objects
        .filter(name='Pending', balance_effect=ChequeStatus.BalanceEffect.NONE, is_active=True)
        .first()
    )
    if pending_status is None:
        pending_status = ChequeStatus.objects.filter(balance_effect=ChequeStatus.BalanceEffect.NONE, is_active=True).first()
    if pending_status is None:
        raise ValueError('At least one non-settling cheque status is required before recording cheque payments.')
    cheque = create_cheque(
        user=user,
        cheque_number=cheque_data['cheque_number'],
        customer=payment.customer,
        name_on_cheque=cheque_data.get('name_on_cheque') or payment.customer.name,
        bank_name=cheque_data['bank_name'],
        branch_name=cheque_data.get('branch_name', ''),
        account_title=cheque_data.get('account_title', ''),
        amount=component.amount,
        cheque_date=cheque_data['cheque_date'],
        expiry_date=cheque_data['expiry_date'],
        received_date=cheque_data.get('received_date') or payment.payment_date,
        status=pending_status,
        notes=cheque_data.get('notes') or f'Created from customer payment {payment.payment_number}',
    )
    component.cheque = cheque
    component.bank_name = cheque.bank_name
    component.save(update_fields=['cheque', 'bank_name', 'updated_at'])
    return cheque


@transaction.atomic
def record_customer_payment(*, user, customer, payment_date, components, reference='', notes='') -> CustomerPayment:
    normalized_components = []
    total = Decimal('0.00')
    for component in components:
        amount = Decimal(component.get('amount') or 0).quantize(Decimal('0.01'))
        if amount <= 0:
            continue
        method = component['method']
        normalized_components.append({**component, 'amount': amount})
        total += amount
    if total <= 0:
        raise ValueError('Payment total must be greater than zero.')

    payment = CustomerPayment.objects.create(
        payment_number=next_customer_payment_number(),
        customer=customer,
        payment_date=payment_date,
        kind=_payment_kind_for_components(normalized_components),
        total_amount=total,
        reference=reference,
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    for data in normalized_components:
        method = data['method']
        component = CustomerPaymentComponent.objects.create(
            payment=payment,
            method=method,
            amount=data['amount'],
            reference=data.get('reference', ''),
            bank_name=data.get('bank_name', ''),
            notes=data.get('notes', ''),
            created_by=user,
            updated_by=user,
        )
        if method == CustomerPaymentComponent.Method.CHEQUE:
            _create_component_cheque(user=user, payment=payment, component=component, cheque_data=data.get('cheque') or data)
            continue

        entry_type = CustomerLedgerEntry.EntryType.WRITE_OFF if method == CustomerPaymentComponent.Method.WRITE_OFF else CustomerLedgerEntry.EntryType.PAYMENT
        method_label = CustomerPaymentComponent.Method(method).label
        CustomerLedgerEntry.objects.create(
            customer=customer,
            entry_date=payment_date,
            entry_type=entry_type,
            description=f'{method_label} recorded via {payment.payment_number}',
            credit=component.amount,
            payment=payment,
            created_by=user,
            updated_by=user,
        )
        _allocate_component_to_oldest_sales(user=user, component=component)

    AuditLog.objects.create(
        actor=user,
        action='customer_payment.created',
        entity_type='CustomerPayment',
        entity_id=str(payment.id),
        message=f'Recorded payment {payment.payment_number} for {customer.name}',
        metadata={'amount': str(payment.total_amount), 'kind': payment.kind},
    )
    return payment


@transaction.atomic
def change_cheque_status(*, user, cheque: Cheque, status: ChequeStatus, notes='') -> Cheque:
    cheque = Cheque.objects.select_for_update().select_related('status', 'customer').get(id=cheque.id)
    previous_status = cheque.status
    if previous_status_id := getattr(previous_status, 'id', None):
        if previous_status_id == status.id:
            if status.balance_effect == ChequeStatus.BalanceEffect.SETTLES_BALANCE:
                _post_cheque_settlement(user=user, cheque=cheque)
            return cheque

    cheque.status = status
    cheque.updated_by = user
    cheque.save(update_fields=['status', 'updated_by', 'updated_at'])

    ChequeStatusHistory.objects.create(
        cheque=cheque,
        from_status=previous_status,
        to_status=status,
        notes=notes,
        created_by=user,
        updated_by=user,
    )

    if status.balance_effect == ChequeStatus.BalanceEffect.SETTLES_BALANCE:
        _post_cheque_settlement(user=user, cheque=cheque)
    elif status.balance_effect == ChequeStatus.BalanceEffect.REVERSES_SETTLEMENT:
        settled = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_SETTLEMENT).exists()
        reversed_once = cheque.ledger_entries.filter(entry_type=CustomerLedgerEntry.EntryType.CHEQUE_REVERSAL).exists()
        if settled and not reversed_once:
            cheque.settlement_allocations.filter(is_reversed=False).update(
                is_reversed=True,
                reversed_at=timezone.now(),
                updated_by=user,
            )
            CustomerLedgerEntry.objects.create(
                customer=cheque.customer,
                entry_date=cheque.received_date or timezone.localdate(),
                entry_type=CustomerLedgerEntry.EntryType.CHEQUE_REVERSAL,
                description=f'Cheque reversal {cheque.cheque_number}',
                debit=cheque.amount,
                cheque=cheque,
                created_by=user,
                updated_by=user,
            )

    AuditLog.objects.create(
        actor=user,
        action='cheque.status_changed',
        entity_type='Cheque',
        entity_id=str(cheque.id),
        message=f'Changed cheque {cheque.cheque_number} status to {status.name}',
        metadata={'from': previous_status.name, 'to': status.name},
    )
    return cheque
