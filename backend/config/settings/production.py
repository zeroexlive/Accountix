import os

from .base import *  # noqa: F403

DEBUG = False
if SECRET_KEY == "dev-only-insecure-key-change-me":  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be set in production")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "true").lower() == "true"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
