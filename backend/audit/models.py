from django.conf import settings
from django.db import models

from core_models import TimeStampedModel


class AuditLog(TimeStampedModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='audit_logs',
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=80)
    entity_type = models.CharField(max_length=120)
    entity_id = models.CharField(max_length=80)
    message = models.CharField(max_length=255)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action']),
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.action} {self.entity_type}:{self.entity_id}'

# Create your models here.
