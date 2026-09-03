from django.utils.text import slugify

from catalog.models import DropdownOption


def ensure_dropdown_option(*, group: str, label: str, user=None):
    label = (label or '').strip()
    if not label:
        return None
    option, created = DropdownOption.objects.get_or_create(
        group=group,
        value=slugify(label),
        defaults={
            'label': label,
            'is_active': True,
            'created_by': user if user and user.is_authenticated else None,
            'updated_by': user if user and user.is_authenticated else None,
        },
    )
    if not created and option.label != label:
        option.label = label
        option.updated_by = user if user and user.is_authenticated else option.updated_by
        option.save(update_fields=['label', 'updated_by', 'updated_at'])
    return option
