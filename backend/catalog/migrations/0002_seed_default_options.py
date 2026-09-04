from django.db import migrations
from django.utils.text import slugify


OPTION_GROUPS = {
    'bank': [
        'Al Baraka Bank (Pakistan) Limited',
        'Allied Bank Limited',
        'Askari Bank Limited',
        'Bank AL Habib Limited',
        'Bank Alfalah Limited',
        'BankIslami Pakistan Limited',
        'Bank Makramah Limited',
        'Citibank N.A.',
        'Deutsche Bank AG',
        'Dubai Islamic Bank Pakistan Limited',
        'Faysal Bank Limited',
        'First Women Bank Limited',
        'Habib Bank Limited',
        'Habib Metropolitan Bank Limited',
        'Industrial and Commercial Bank of China Limited',
        'JS Bank Limited',
        'MCB Bank Limited',
        'MCB Islamic Bank Limited',
        'Meezan Bank Limited',
        'National Bank of Pakistan',
        'Sindh Bank Limited',
        'Soneri Bank Limited',
        'Standard Chartered Bank (Pakistan) Limited',
        'The Bank of Khyber',
        'The Bank of Punjab',
        'United Bank Limited',
        'Zarai Taraqiati Bank Limited',
    ],
    'part_name': [
        'Toyota headlight pair',
        'Honda front bumper',
        'Nissan alternator',
        'Mazda side mirror',
        'Suzuki tail light',
        'Engine assembly',
        'Transmission',
        'ABS pump',
        'Shock set',
    ],
    'item_category': ['Body parts', 'Electrical', 'Engine', 'Lights', 'Suspension', 'Transmission'],
    'item_condition': ['Unknown', 'Used', 'New', 'Damaged'],
    'item_unit': ['piece', 'set', 'pair', 'kg', 'box'],
}


def seed_options(apps, schema_editor):
    DropdownOption = apps.get_model('catalog', 'DropdownOption')
    for group, labels in OPTION_GROUPS.items():
        for index, label in enumerate(labels):
            DropdownOption.objects.update_or_create(
                group=group,
                value=slugify(label),
                defaults={
                    'label': label,
                    'is_system': True,
                    'is_active': True,
                    'sort_order': index,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ('catalog', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_options, migrations.RunPython.noop),
    ]
