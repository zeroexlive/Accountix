#!/usr/bin/env bash
# Build the Accountix standalone bundle for Linux (Sprint 09).
# Produces dist/accountix/accountix (onedir). See docs/deployment/LINUX.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
"$PY" -m venv .venv-build
.venv-build/bin/pip install --upgrade pip
.venv-build/bin/pip install -e ".[dev]"

# Compile the gettext catalogs so the bundle ships .mo files next to
# the committed .po sources (Sprint 19, ADR-045). Requires the gettext
# tools (msgfmt) on the BUILD machine — a hard prerequisite here,
# unlike end-user machines where compilation is best effort.
(cd backend && DJANGO_SETTINGS_MODULE=config.settings.local ../.venv-build/bin/python manage.py compilemessages)

.venv-build/bin/pyinstaller launcher/accountix.spec \
    --noconfirm \
    --distpath dist \
    --workpath build/pyinstaller

echo "Built: $ROOT/dist/accountix/accountix"
echo "Smoke it with: ACCOUNTIX_DATA_DIR=/tmp/accountix-bundle-smoke ACCOUNTIX_NO_BROWSER=1 dist/accountix/accountix"
