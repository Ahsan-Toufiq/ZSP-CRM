from django.db import migrations


CLIENT_USERNAME = 'syed.zulfiqar'


def remove_automatic_client_currency_access(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    profile = UserProfile.objects.select_related('user').filter(user__username=CLIENT_USERNAME).first()
    if profile is None:
        return
    permissions = dict(profile.tab_permissions or {})
    permissions.pop('currency', None)
    profile.tab_permissions = permissions
    profile.save(update_fields=['tab_permissions'])


def restore_client_currency_access(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    profile = UserProfile.objects.select_related('user').filter(user__username=CLIENT_USERNAME).first()
    if profile is None:
        return
    permissions = dict(profile.tab_permissions or {})
    permissions['currency'] = 'full'
    profile.tab_permissions = permissions
    profile.save(update_fields=['tab_permissions'])


class Migration(migrations.Migration):
    dependencies = [('accounts', '0003_grant_currency_access_to_handover_users')]

    operations = [
        migrations.RunPython(remove_automatic_client_currency_access, restore_client_currency_access),
    ]
