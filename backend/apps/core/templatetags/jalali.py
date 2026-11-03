"""Jalali (Persian calendar) display filter (Sprint 13, ADR-040).

Display-only layer: every stored date and every form input stays
Gregorian; templates render dates through ``|jalali`` to show the
Jalali equivalent as ``YYYY/MM/DD`` with Latin digits — the digit
convention the UI already uses for amounts and identifiers. The
conversion is delegated to the ``jdatetime`` library (pure Python);
``None`` renders empty so ``|default:"—"`` chains keep working, and
non-date values pass through untouched.
"""

import datetime

import jdatetime
from django import template

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


@register.filter(name="jalali")
def jalali_filter(value):
    return to_jalali(value)
