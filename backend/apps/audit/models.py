from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedUUIDModel
from apps.organizations.models import Company


class AuditEvent(TimeStampedUUIDModel):
    """Append-only audit record. Business services write these explicitly;
    Sprint 01 provides the model and a helper — no automatic logging yet."""

    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_events"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} {self.entity_type} {self.entity_id}"
