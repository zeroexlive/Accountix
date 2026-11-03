"""Jalali (Persian calendar) display filter (Sprint 13, ADR-040).

Display-only layer: every stored date and every form input stays
Gregorian; templates render dates through ``|jalali`` to show the
Jalali equivalent as ``YYYY/MM/DD`` with Latin digits — the digit
convention the UI already uses for amounts and identifiers. The
conversion is delegated to the ``jdatetime`` library (pure Python);
``None`` renders empty so ``|default:"—"`` chains keep working, and
non-date values pass through untouched.

Sprint 19 (ADR-045) made the filter language-aware, here in its one
implementation: while the active language is Persian (or unset) the
output is exactly the Jalali rendering above; under any other active
language (currently English) the stored Gregorian date is shown in
neutral ISO form ``YYYY-MM-DD``. The filter keeps its ``jalali``
name — renaming it would mean touching every template for a purely
cosmetic gain; the naming debt is recorded in ADR-045.
"""

import datetime

import jdatetime
from django import template
from django.utils import translation

register = template.Library()


def to_jalali(value):
    """Gregorian ``date``/``datetime`` → ``"1405/03/11"`` (or ``""``).

    Returns the input unchanged when it is not a date at all, so a
    stray string in a template never breaks rendering.
    """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        value = value.date()
    if not isinstance(value, datetime.date):
        return value
    converted = jdatetime.date.fromgregorian(day=value.day, month=value.month, year=value.year)
    return f"{converted.year:04d}/{converted.month:02d}/{converted.day:02d}"


def to_gregorian_iso(value):
    """Gregorian ``date``/``datetime`` → ``"2026-03-20"`` (or ``""``).

    Same pass-through contract as :func:`to_jalali`: ``None`` renders
    empty and non-date values are returned unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        value = value.date()
    if not isinstance(value, datetime.date):
        return value
    return value.isoformat()


@register.filter(name="jalali")
def jalali_filter(value):
    language = translation.get_language()
    if language and not language.startswith("fa"):
        return to_gregorian_iso(value)
    return to_jalali(value)
