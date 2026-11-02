from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedUUIDModel
from apps.organizations import services


class Company(TimeStampedUUIDModel):
    name = models.CharField(max_length=200)
    legal_name = models.CharField(max_length=200, blank=True)
    registration_number = models.CharField(max_length=64, blank=True)
    default_currency = models.CharField(max_length=3, default="IRR")  # ISO 4217
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Branch(TimeStampedUUIDModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_branch_code_per_company")
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.company} / {self.name}"


class CompanyMembership(TimeStampedUUIDModel):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ADMIN = "ADMIN", "Admin"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        SALES = "SALES", "Sales operator"
        PURCHASES = "PURCHASES", "Purchasing operator"
        WAREHOUSE = "WAREHOUSE", "Warehouse manager"
        CASHIER = "CASHIER", "Cashier"
        VIEWER = "VIEWER", "Viewer"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="company_memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "user"], name="uniq_membership_per_company_user"
            )
        ]

    def __str__(self):
        return f"{self.user} @ {self.company} ({self.role})"


class FiscalYear(TimeStampedUUIDModel):
    """Fiscal years and periods live in organizations in Sprint 01: they are
    company-scoped master data that the accounting engine (Sprint 02) consumes.
    Documented in docs/architecture/DECISIONS.md (ADR-004)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="fiscal_years")
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="fiscal_year_end_gte_start",
            )
        ]

    def clean(self):
        super().clean()
        services.validate_fiscal_year(self)

    def __str__(self):
        return f"{self.company} / {self.name}"


class FiscalPeriod(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="fiscal_periods")
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name="periods")
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="fiscal_period_end_gte_start",
            )
        ]

    def clean(self):
        super().clean()
        services.validate_fiscal_period(self)

    def __str__(self):
        return f"{self.fiscal_year} / {self.name}"
