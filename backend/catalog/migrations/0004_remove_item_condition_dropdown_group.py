from django.db import migrations, models


def remove_condition_options(apps, schema_editor):
    DropdownOption = apps.get_model('catalog', 'DropdownOption')
    DropdownOption.objects.filter(group='item_condition').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0003_alter_dropdownoption_group'),
    ]

    operations = [
        migrations.RunPython(remove_condition_options, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='dropdownoption',
            name='group',
            field=models.CharField(choices=[('bank', 'Bank'), ('part_name', 'Part name'), ('item_category', 'Item category'), ('item_unit', 'Item unit')], max_length=40),
        ),
    ]
