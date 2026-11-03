"""Base settings for Accountix. Secrets come from environment variables only."""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/
PROJECT_ROOT = BASE_DIR.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = False
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "axes",
    "apps.core",
    "apps.users",
    "apps.organizations",
    "apps.accounting",
    "apps.audit",
    "apps.catalog",
    "apps.inventory",
    "apps.parties",
    "apps.purchases",
    "apps.sales",
    "apps.treasury",
    "apps.reporting",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # AxesMiddleware must be LAST (django-axes installation docs): it only
    # rewrites the response of a login attempt that axes has locked out.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.company_roles",
            ],
        },
    },
]


def database_from_env() -> dict:
    """SQLite by default; PostgreSQL when DATABASE_URL is a postgres URL.

    Hand-rolled parser so no extra dependency is needed for the two
    supported backends. Do not assume SQLite and PostgreSQL lock alike.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith(("postgres://", "postgresql://")):
        parsed = urlparse(url)
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/") or "accountix",
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "127.0.0.1",
            "PORT": str(parsed.port or 5432),
        }
    data_dir = Path(os.environ.get("ACCOUNTIX_DATA_DIR", PROJECT_ROOT))
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(data_dir / "db.sqlite3"),
    }


DATABASES = {"default": database_from_env()}

AUTH_USER_MODEL = "users.User"

# Password validation (Sprint 10 security review): the four standard
# Django validators. Before Sprint 10 this setting was absent entirely,
# so Django's default (no validators) applied and any password — even
# "password" — was accepted by create_user / admin / password change.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# First-run setup (Sprint 24, ADR-049): while the user table is empty,
# /login/ redirects to a one-time /setup/ page that creates the first
# admin + company, so a bundle-only recipient can bootstrap without a
# source checkout. The zero-user window is first-come-first-served by
# design, so a deployment exposed to a network before its first login
# must pre-create the admin (createsuperuser) or disable setup:
# ACCOUNTIX_FIRST_RUN_SETUP=0 turns the redirect off entirely and
# /setup/ then redirects to /login/ even with zero users.
FIRST_RUN_SETUP_ENABLED = os.environ.get("ACCOUNTIX_FIRST_RUN_SETUP", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# Authentication backends (Sprint 16, ADR-043): django-axes monitors the
# login flow. AxesStandaloneBackend must be FIRST (axes installation
# docs): it refuses authentication for locked-out clients and delegates
# the actual credential check to ModelBackend, which stays second.
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Login throttling (Sprint 16, ADR-043) — django-axes, closing release
# gate #20. Policy: after AXES_FAILURE_LIMIT failed logins for the same
# (username, IP address) combination, that combination is locked out
# for the cooloff — even the correct password is refused until the
# cooloff expires or an admin resets the attempt (Django admin → Axes →
# Access attempts, or `manage.py axes_reset_ip_username`). A successful
# login resets the counter. Both knobs are env-overridable like the
# other settings in this module.
AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", "5"))
AXES_COOLOFF_TIME = timedelta(hours=float(os.environ.get("AXES_COOLOFF_HOURS", "1")))
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "registration/lockout.html"
# Axes 9 defaults the lockout response to 429; 403 is the documented
# behaviour this product shipped its lockout page for.
AXES_HTTP_RESPONSE_CODE = 403
# Client-IP resolution: REMOTE_ADDR only. django-ipware is deliberately
# NOT installed, so axes falls back to request.META["REMOTE_ADDR"] and
# X-Forwarded-For is never trusted — a client cannot spoof its way out
# of (or into) a lockout. A deployment behind a reverse proxy must opt
# in explicitly: install django-axes[ipware] and set
# AXES_IPWARE_PROXY_COUNT / AXES_IPWARE_PROXY_TRUSTED_IPS /
# AXES_IPWARE_META_PRECEDENCE_ORDER for its own proxy chain (see
# docs/deployment/PRODUCTION.md).
AXES_IPWARE_META_PRECEDENCE_ORDER = ("REMOTE_ADDR",)

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True
# Bilingual UI (Sprint 19, ADR-045): Persian is the default and the
# source language — template msgids ARE the Persian literals, so the
# fa catalog needs no translations (an untranslated msgid renders as
# itself, i.e. Persian). English lives in locale/en. Language is
# carried by Django's language cookie via LocaleMiddleware (already
# above, between Session and Common) and the set_language view wired
# in config.urls — deliberately NOT by i18n_patterns URL prefixes, so
# every existing URL stays stable. Catalogs are committed as .po
# only; .mo files are build/startup artifacts (see ADR-045).
LANGUAGES = [("fa", "فارسی"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # templates/JS need the token cookie pattern documented by Django

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
