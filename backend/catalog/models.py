from django.db import models
from django.utils.text import slugify

from core_models import UserStampedModel


class DropdownOption(UserStampedModel):
    class Group(models.TextChoices):
        BANK = 'bank', 'Bank'
        ITEM_CATEGORY = 'item_category', 'Item category'
        ITEM_CONDITION = 'item_condition', 'Item condition'
        ITEM_UNIT = 'item_unit', 'Item unit'

    group = models.CharField(max_length=40, choices=Group.choices)
    label = models.CharField(max_length=160)
    value = models.SlugField(max_length=180)
    is_system = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ['group', 'sort_order', 'label']
        constraints = [
            models.UniqueConstraint(fields=['group', 'label'], name='unique_option_label_per_group'),
            models.UniqueConstraint(fields=['group', 'value'], name='unique_option_value_per_group'),
        ]
        indexes = [
            models.Index(fields=['group', 'is_active']),
        ]

    def save(self, *args, **kwargs):
        if not self.value:
            self.value = slugify(self.label)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.get_group_display()}: {self.label}'
