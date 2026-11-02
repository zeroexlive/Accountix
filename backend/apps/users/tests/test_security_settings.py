"""Security-settings regression tests (Sprint 10).

Before Sprint 10, AUTH_PASSWORD_VALIDATORS was absent from the project
settings, so Django applied no password validation at all. These tests
pin the fix so the setting cannot silently disappear again.
"""

import pytest
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


def test_password_validators_configured():
    names = [v["NAME"] for v in settings.AUTH_PASSWORD_VALIDATORS]
    assert any("MinimumLengthValidator" in n for n in names)
    assert any("CommonPasswordValidator" in n for n in names)
    assert any("NumericPasswordValidator" in n for n in names)
    assert any("UserAttributeSimilarityValidator" in n for n in names)


def test_common_password_rejected():
    with pytest.raises(ValidationError):
        validate_password("password")


def test_entirely_numeric_password_rejected():
    with pytest.raises(ValidationError):
        validate_password("12345678901")


def test_short_password_rejected():
    with pytest.raises(ValidationError):
        validate_password("aB3!x")


def test_strong_password_accepted():
    validate_password("Tr7!qzv#9Lm2wX")
