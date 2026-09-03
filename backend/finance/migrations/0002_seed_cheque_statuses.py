from django.db import migrations


def seed_statuses(apps, schema_editor):
    ChequeStatus = apps.get_model('finance', 'ChequeStatus')
    statuses = [
        ('Settle for Cash', 'settles_balance'),
        ('Bounced', 'reverses_settlement'),
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


def unseed_statuses(apps, schema_editor):
    ChequeStatus = apps.get_model('finance', 'ChequeStatus')
    ChequeStatus.objects.filter(name__in=['Settle for Cash', 'Bounced', 'Cleared']).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_statuses, unseed_statuses),
    ]
