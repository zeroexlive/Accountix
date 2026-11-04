#!/usr/bin/env bash
# Tour DOM check runner (Sprint 31, ADR-059).
#
# Dumps REAL rendered pages (populated crawl world, fa + en) via
# dump_pages.py, then executes the real tour.js against them in
# jsdom (harness.mjs): CSS-cascade contract for the hidden start
# button, engine reveal, click-through of every step, prev, Esc,
# and any uncaught JS error fails the run.
#
# jsdom is a dev-only harness dependency: it is npm-installed into
# a scratch dir OUTSIDE the repo (never vendored, never shipped).
#
# Usage: scripts/tour_dom_check/run.sh
# Env:   TOUR_HARNESS_DIR — scratch dir (default /tmp/accountix-tour-harness)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HARNESS="${TOUR_HARNESS_DIR:-/tmp/accountix-tour-harness}"
mkdir -p "$HARNESS/pages"

if [ ! -d "$HARNESS/node_modules/jsdom" ]; then
  (cd "$HARNESS" && npm init -y >/dev/null 2>&1 && npm install jsdom@24 --no-audit --no-fund)
fi
cp "$ROOT/scripts/tour_dom_check/harness.mjs" "$HARNESS/harness.mjs"
cp "$ROOT/scripts/tour_dom_check/scan_harness.mjs" "$HARNESS/scan_harness.mjs"

cd "$ROOT"
TOUR_DUMP_DIR="$HARNESS/pages" .venv/bin/python -m pytest \
  scripts/tour_dom_check/dump_pages.py scripts/tour_dom_check/dump_scan_page.py -q
cd "$HARNESS"
node harness.mjs pages "$ROOT/backend/static"
node scan_harness.mjs pages "$ROOT/backend/static"
