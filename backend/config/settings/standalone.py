"""Standalone (packaged desktop) settings.

Used by the launcher / PyInstaller bundle for the offline-first local
installation (master prompt sections 16-17):

- SQLite database inside the per-user data directory (see config.paths).
- SECRET_KEY generated once into the data directory, never committed.
- DEBUG off; hosts limited to loopback; binds happen in serve.py.
- Static files are collected into the data directory and served by
  WhiteNoise, so the frozen app needs no separate static server.
- Session/CSRF cookies are *not* marked Secure here: the app is served
  over plain HTTP on 127.0.0.1 only, where a Secure cookie would never be
  sent back by the browser and login would break. This is deliberately
  different from config.settings.production (public HTTPS). See ADR-033.
"""

import os

from config.paths import data_dir, ensure_data_dir, get_or_create_secret_key, static_root

_DATA_DIR = ensure_data_dir(data_dir())

# base.database_from_env() resolves the SQLite path from this variable.
os.environ["ACCOUNTIX_DATA_DIR"] = str(_DATA_DIR)

from .base import *  # noqa: E402,F403

SECRET_KEY = get_or_create_secret_key(_DATA_DIR)
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(_DATA_DIR / "db.sqlite3"),
    }
}

STATIC_ROOT = static_root(_DATA_DIR)
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
