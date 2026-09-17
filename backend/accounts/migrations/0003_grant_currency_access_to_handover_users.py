from django.db import migrations


HANDOVER_USERNAMES = {'admin', 'syed.zulfiqar'}


def grant_currency_access(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    profiles = UserProfile.objects.select_related('user').filter(user__username__in=HANDOVER_USERNAMES)
    for profile in profiles:
        permissions = dict(profile.tab_permissions or {})
        permissions['currency'] = 'full'
        profile.tab_permissions = permissions
        profile.save(update_fields=['tab_permissions'])


def remove_currency_access(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    profiles = UserProfile.objects.select_related('user').filter(user__username__in=HANDOVER_USERNAMES)
    for profile in profiles:
        permissions = dict(profile.tab_permissions or {})
        permissions.pop('currency', None)
        profile.tab_permissions = permissions
        profile.save(update_fields=['tab_permissions'])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_userprofile_tab_permissions'),
        ('finance', '0007_alter_customerledgerentry_entry_type_currency_and_more'),
    ]

    operations = [
        migrations.RunPython(grant_currency_access, remove_currency_access),
    ]
