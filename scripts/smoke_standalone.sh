#!/usr/bin/env bash
# Standalone launcher smoke test (Sprint 09).
#
# Launches the real launcher twice against a throwaway data directory:
#   1st launch: fresh DB -> migrate -> serve -> /health/ + /login/ checks
#   2nd launch: existing DB -> a pre-migration backup must appear
# The browser is disabled (ACCOUNTIX_NO_BROWSER=1). Nothing outside the
# temp data dir is touched. Usage: scripts/smoke_standalone.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PORT="${ACCOUNTIX_SMOKE_PORT:-8877}"
DATA="$(mktemp -d /tmp/accountix-smoke-XXXXXX)"
export ACCOUNTIX_DATA_DIR="$DATA"
export ACCOUNTIX_NO_BROWSER=1
export ACCOUNTIX_PORT="$PORT"
HEALTH="http://127.0.0.1:${PORT}/health/"

cleanup() {
    [ -n "${LPID:-}" ] && kill -INT "$LPID" 2>/dev/null || true
    [ -n "${LPID:-}" ] && wait "$LPID" 2>/dev/null || true
    LPID=""
}
trap cleanup EXIT

wait_health() {
    for _ in $(seq 1 60); do
        if curl -fsS "$HEALTH" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    echo "FAIL: server did not become healthy on $HEALTH" >&2
    tail -20 "$DATA/accountix.log" >&2 || true
    exit 1
}

echo "== data dir: $DATA (port $PORT)"

echo "== first launch (fresh database)"
"$PY" "$ROOT/launcher/accountix_launcher.py" &
LPID=$!
wait_health
echo "health: $(curl -fsS "$HEALTH")"
curl -fsS "http://127.0.0.1:${PORT}/login/" | grep -qi "<html" && echo "login page: served"
for f in db.sqlite3 secret_key.txt accountix.log; do
    [ -f "$DATA/$f" ] && echo "present: $f" || { echo "FAIL: missing $f" >&2; exit 1; }
done
cleanup
sleep 1

echo "== second launch (existing database -> backup expected)"
"$PY" "$ROOT/launcher/accountix_launcher.py" &
LPID=$!
wait_health
ls "$DATA"/backups/accountix-*.sqlite3 >/dev/null 2>&1 \
    && echo "pre-migration backup: $(ls "$DATA"/backups/)" \
    || { echo "FAIL: no backup created on second launch" >&2; exit 1; }
cleanup

echo "SMOKE OK"
