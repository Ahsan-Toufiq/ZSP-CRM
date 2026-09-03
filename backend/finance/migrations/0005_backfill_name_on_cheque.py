from django.db import migrations


def backfill_name_on_cheque(apps, schema_editor):
    Cheque = apps.get_model('finance', 'Cheque')
    for cheque in Cheque.objects.select_related('customer').filter(name_on_cheque=''):
        cheque.name_on_cheque = cheque.customer.name
        cheque.save(update_fields=['name_on_cheque'])


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0004_cheque_name_on_cheque_alter_cheque_received_date'),
    ]

    operations = [
        migrations.RunPython(backfill_name_on_cheque, migrations.RunPython.noop),
    ]
