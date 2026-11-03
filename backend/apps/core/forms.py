"""Shared form helpers for the data-entry UI (Sprint 12, ADR-039).

The UI never swallows service errors: a ``ValidationError`` raised by
a service is attached to the form as non-field errors so the user sees
the service's own message and nothing is persisted (services validate
before writing and run in their own transaction).
"""

from django.core.exceptions import ValidationError


def add_service_errors(form, exc: ValidationError) -> None:
    """Attach a service-layer ValidationError to a form for display."""
    for message in exc.messages:
        form.add_error(None, message)


def date_widget():
    """The date input used by the Sprint 08 filter forms."""
    from django import forms

    return forms.DateInput(attrs={"type": "date"})
