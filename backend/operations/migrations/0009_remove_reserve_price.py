from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0008_remove_part_condition_and_merge_part_identity'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='containeritem',
            name='reserve_price',
        ),
        migrations.RemoveField(
            model_name='partinventory',
            name='reserve_price',
        ),
    ]
