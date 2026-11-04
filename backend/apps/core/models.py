"""Shared base models + phone-scan pairing (Sprint 31, ADR-060)."""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedUUIDModel(models.Model):
    """Abstract base: UUID primary key + created/updated timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ScanSession(TimeStampedUUIDModel):
    """A phone-pairing session for invoice scanning (ADR-060).

    A desktop user (OPERATE tier) creates a session bound to one
    company; the raw token is shown once (link + QR) and only its
    SHA-256 hash is stored — the token IS the phone's credential,
    so the database never holds a usable copy. Sessions live 10
    minutes and can be revoked from the desktop, which kills the
    token immediately.
    """

    token_hash = models.CharField(max_length=64, unique=True)
    company = models.ForeignKey(
        "organizations.Company", on_delete=models.CASCADE, related_name="scan_sessions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scan_sessions"
    )
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def is_live(self) -> bool:
        return not self.revoked and self.expires_at > timezone.now()

    def __str__(self):
        return f"ScanSession({self.company_id}, by {self.created_by_id}, live={self.is_live()})"


class ScanSubmission(TimeStampedUUIDModel):
    """One code scanned by the paired phone, resolved server-side
    to a product of the session's company at submission time (so
    the phone user gets immediate not-found feedback, and nothing
    unresolvable ever reaches the desktop). The desktop polls and
    consumes each submission exactly once."""

    session = models.ForeignKey(
        ScanSession, on_delete=models.CASCADE, related_name="submissions"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="scan_submissions"
    )
    code = models.CharField(max_length=64)
    consumed = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]
