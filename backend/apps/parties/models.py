"""Party master data (Sprint 04, ADR-014 follow-up).

A ``Party`` is a company-scoped counterparty: a supplier, a customer, or
both (one row with ``kind=BOTH`` rather than duplicate rows per role).
Contacts and addresses hang off the party and inherit its company scope —
they carry no company FK of their own, so company isolation is enforced
through the party, exactly as journal subledger tagging references the
party (see accounting ADR-015).
"""

from django.db import models

from apps.core.models import TimeStampedUUIDModel
from apps.organizations.models import Company
from apps.parties import services


class Party(TimeStampedUUIDModel):
    class Kind(models.TextChoices):
        SUPPLIER = "SUPPLIER", "Supplier"
        CUSTOMER = "CUSTOMER", "Customer"
        BOTH = "BOTH", "Supplier and customer"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="parties")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SUPPLIER)
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    # Optional plain identifiers — no format is enforced in this sprint:
    # Iranian economic code / national id formats vary by party type and
    # hardcoding one jurisdiction's validation would be wrong (prompt §12).
    tax_id = models.CharField(max_length=64, blank=True)
    registration_number = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_party_code_per_company")
        ]

    @property
    def is_supplier(self) -> bool:
        return self.kind in (self.Kind.SUPPLIER, self.Kind.BOTH)

    @property
    def is_customer(self) -> bool:
        return self.kind in (self.Kind.CUSTOMER, self.Kind.BOTH)

    def clean(self):
        super().clean()
        services.validate_party(self)

    def __str__(self):
        return f"{self.code} — {self.name}"


class PartyContact(TimeStampedUUIDModel):
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="contacts")
    full_name = models.CharField(max_length=200)
    role = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.party.code})"


class PartyAddress(TimeStampedUUIDModel):
    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=100, blank=True)
    line1 = models.CharField(max_length=300, blank=True)
    line2 = models.CharField(max_length=300, blank=True)
    city = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=2, blank=True)  # ISO 3166-1 alpha-2 when known

    class Meta:
        ordering = ["label", "city"]

    def __str__(self):
        return f"{self.party.code}: {self.label or self.city}"
