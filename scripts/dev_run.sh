#!/usr/bin/env bash
# One-command dev startup for a source clone (Sprint 31, ADR-058).
#
# Why this exists: the app is bilingual and Django reads COMPILED
# catalogs (.mo), while the repo ships .po sources. Starting plain
# `runserver` on a fresh pull leaves both languages silently
# falling back to source strings — Persian text inside English
# pages AND English text inside Persian pages. The launcher and
# the test suite compile automatically; this script gives a dev
# clone the same guarantee:
#
#   1. msgfmt present?  (hard fail with the install hint otherwise)
#   2. compilemessages  (catalogs fresh, both languages whole)
#   3. migrate          (schema current)
#   4. runserver "$@"   (extra args pass through, e.g. 0.0.0.0:8765)
#
# Usage: scripts/dev_run.sh [runserver args...]
# Env:   PYTHON — interpreter to use (default: .venv/bin/python if
#        present, else python3). DJANGO_SETTINGS_MODULE respected
#        (default: the manage.py default, config.settings.local).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="${PYTHON:-$ROOT/.venv/bin/python}"
else
  PY="${PYTHON:-python3}"
fi

if ! command -v msgfmt >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: GNU gettext (msgfmt) is not installed — translation catalogs
cannot be compiled and both languages will render wrong.
  Debian/Ubuntu: sudo apt-get install -y gettext
  (scoped update if the mirror is slow:
   sudo apt-get update -o Acquire::Languages=none)
خطا: ابزار gettext (msgfmt) نصب نیست؛ بدون آن کاتالوگ‌های ترجمه
کامپایل نمی‌شوند و هر دو زبان ناقص نمایش داده می‌شوند.
  نصب در دبیان/اوبونتو: sudo apt-get install -y gettext
EOF
  exit 1
fi

"$PY" manage.py compilemessages
"$PY" manage.py migrate
exec "$PY" manage.py runserver "$@"
