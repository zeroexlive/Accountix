"""Application services for organization / fiscal rules.

Validation that spans records (overlaps) lives here, not in views, so the
same rules apply to forms, the API and future importers.
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_date_range(start, end, *, start_label="Start date", end_label="End date"):
    if start and end and start > end:
        raise ValidationError(
            _("%(start_label)s must be on or before %(end_label)s.")
            % {"start_label": start_label, "end_label": end_label}
        )


def fiscal_years_overlap(company_id, start, end, *, exclude_id=None) -> bool:
    from apps.organizations.models import FiscalYear

    qs = FiscalYear.objects.filter(company_id=company_id, start_date__lte=end, end_date__gte=start)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def fiscal_periods_overlap(fiscal_year_id, start, end, *, exclude_id=None) -> bool:
    from apps.organizations.models import FiscalPeriod

    qs = FiscalPeriod.objects.filter(
        fiscal_year_id=fiscal_year_id, start_date__lte=end, end_date__gte=start
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def validate_fiscal_year(instance) -> None:
    validate_date_range(instance.start_date, instance.end_date)
    if (
        instance.start_date
        and instance.end_date
        and fiscal_years_overlap(
            instance.company_id, instance.start_date, instance.end_date, exclude_id=instance.pk
        )
    ):
        raise ValidationError(_("Fiscal year overlaps an existing fiscal year for this company."))


def validate_fiscal_period(instance) -> None:
    validate_date_range(instance.start_date, instance.end_date)
    if instance.fiscal_year_id:
        fy = instance.fiscal_year
        if instance.company_id and fy.company_id != instance.company_id:
            raise ValidationError(_("Fiscal period company does not match its fiscal year."))
        if instance.start_date and instance.start_date < fy.start_date:
            raise ValidationError(_("Fiscal period starts before its fiscal year."))
        if instance.end_date and instance.end_date > fy.end_date:
            raise ValidationError(_("Fiscal period ends after its fiscal year."))
        if (
            instance.start_date
            and instance.end_date
            and fiscal_periods_overlap(
                instance.fiscal_year_id,
                instance.start_date,
                instance.end_date,
                exclude_id=instance.pk,
            )
        ):
            raise ValidationError(_("Fiscal period overlaps another period in this fiscal year."))
