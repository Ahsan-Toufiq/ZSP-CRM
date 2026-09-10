from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def backfill_payment_split(apps, schema_editor):
    AuctionSale = apps.get_model('operations', 'AuctionSale')
    Cheque = apps.get_model('finance', 'Cheque')
    for sale in AuctionSale.objects.all().iterator():
        cheque_amount = Cheque.objects.filter(sale=sale).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        if sale.payment_type == 'cash':
            sale.cash_amount = sale.total_amount
            sale.credit_amount = Decimal('0.00')
        else:
            sale.cash_amount = Decimal('0.00')
            sale.credit_amount = max(Decimal(sale.total_amount or 0) - Decimal(cheque_amount or 0), Decimal('0.00'))
        sale.save(update_fields=['cash_amount', 'credit_amount'])


def clear_payment_split(apps, schema_editor):
    AuctionSale = apps.get_model('operations', 'AuctionSale')
    AuctionSale.objects.update(cash_amount=Decimal('0.00'), credit_amount=Decimal('0.00'))


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0011_auctionsale_cash_amount_auctionsale_credit_amount'),
    ]

    operations = [
        migrations.RunPython(backfill_payment_split, clear_payment_split),
    ]
