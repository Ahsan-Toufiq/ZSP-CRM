from django.db import migrations, models


def _merge_text_values(*values):
    labels = []
    seen = set()
    for value in values:
        for label in str(value or '').split(','):
            cleaned = label.strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                labels.append(cleaned)
                seen.add(key)
    return ', '.join(labels)


def merge_duplicate_part_inventory(apps, schema_editor):
    PartInventory = apps.get_model('operations', 'PartInventory')
    InventoryBatch = apps.get_model('operations', 'InventoryBatch')
    AuctionSaleLine = apps.get_model('operations', 'AuctionSaleLine')

    groups = {}
    for part in PartInventory.objects.order_by('created_at', 'id'):
        key = (
            part.part_name,
            part.part_number or '',
            part.unit or 'piece',
        )
        groups.setdefault(key, []).append(part)

    for parts in groups.values():
        if len(parts) < 2:
            continue
        canonical = parts[0]
        duplicates = parts[1:]
        canonical.quantity = sum(int(part.quantity or 0) for part in parts)
        canonical.category = _merge_text_values(*(part.category for part in parts))
        canonical.description = canonical.description or next((part.description for part in duplicates if part.description), '')
        if canonical.reserve_price is None:
            canonical.reserve_price = next((part.reserve_price for part in duplicates if part.reserve_price is not None), None)
        canonical.save(update_fields=['quantity', 'category', 'description', 'reserve_price', 'updated_at'])

        for duplicate in duplicates:
            InventoryBatch.objects.filter(item=duplicate).update(item=canonical)
            AuctionSaleLine.objects.filter(item=duplicate).update(item=canonical)
            duplicate.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0007_auctionsaleline_net_unit_cost_snapshot_and_more'),
    ]

    operations = [
        migrations.RunPython(merge_duplicate_part_inventory, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='partinventory',
            name='unique_sellable_part_inventory',
        ),
        migrations.RemoveField(
            model_name='containeritem',
            name='condition',
        ),
        migrations.RemoveField(
            model_name='partinventory',
            name='condition',
        ),
        migrations.AddConstraint(
            model_name='partinventory',
            constraint=models.UniqueConstraint(fields=('part_name', 'part_number', 'unit'), name='unique_sellable_part_inventory'),
        ),
    ]
