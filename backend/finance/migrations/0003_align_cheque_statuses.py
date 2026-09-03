from django.db import migrations


def align_statuses(apps, schema_editor):
    ChequeStatus = apps.get_model('finance', 'ChequeStatus')
    ChequeStatus.objects.filter(name='Settle for Cash').update(name='Settled by Cash')
    statuses = [
        ('Pending', 'none'),
        ('Bounced', 'reverses_settlement'),
        ('Settled', 'settles_balance'),
        ('Settled by Cash', 'settles_balance'),
        ('Cleared', 'settles_balance'),
    ]
    for name, balance_effect in statuses:
        ChequeStatus.objects.update_or_create(
            name=name,
            defaults={
                'balance_effect': balance_effect,
                'is_system': True,
                'is_active': True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0002_seed_cheque_statuses'),
    ]

    operations = [
        migrations.RunPython(align_statuses, migrations.RunPython.noop),
    ]
