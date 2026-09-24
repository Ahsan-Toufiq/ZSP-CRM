from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0012_backfill_auction_sale_payment_split'),
    ]

    operations = [
        migrations.RenameField(
            model_name='container',
            old_name='manifest_notes',
            new_name='notes',
        ),
        migrations.AddField(
            model_name='container',
            name='current_location',
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name='container',
            name='size_type',
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
