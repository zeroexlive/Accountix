"""PostgreSQL test settings (Sprint 10).

Inherits base (which parses DATABASE_URL via database_from_env) and
only overrides what tests need: fast password hashing and a test
secret. Usage:

    DATABASE_URL=postgresql://postgres@127.0.0.1:54329/accountix_test \
        .venv/bin/python -m pytest --ds=config.settings.postgres_test

If DATABASE_URL is not a postgres URL, base falls back to SQLite —
the concurrency test module skips itself in that case.
"""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-only-secret-key"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
