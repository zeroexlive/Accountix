#!/usr/bin/env bash
# Package the Accountix Linux bundle into a versioned, distributable
# release artifact (Sprint 29, ADR-054). See docs/deployment/LINUX.md.
#
# Input:  dist/accountix/ (the PyInstaller onedir bundle — run
#         scripts/build_linux.sh first).
# Output: release/accountix-<VERSION>-linux.tar.gz
#         release/accountix-<VERSION>-linux.tar.gz.sha256
#
# The archive has a single top-level folder, accountix-<VERSION>-linux/,
# holding the bundle (the `accountix` binary + `_internal/`) plus the
# operator docs an installer needs (LOCAL.md, UPGRADE.md). <VERSION> is
# read from backend/config/version.py — the product's one source of
# truth for its version (ADR-052) — and is never hardcoded here.
# dist/ and release/ are both gitignored: the artifact is a build
# product, identified by its name + checksum, not a committed file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="$(sed -n 's/^__version__ *= *"\([^"]*\)".*/\1/p' backend/config/version.py)"
if [ -z "$VERSION" ]; then
    echo "ERROR: could not parse __version__ from backend/config/version.py" >&2
    exit 1
fi

BUNDLE="dist/accountix"
if [ ! -x "$BUNDLE/accountix" ]; then
    echo "ERROR: bundle not found at $BUNDLE — run scripts/build_linux.sh first." >&2
    exit 1
fi

NAME="accountix-${VERSION}-linux"
RELEASE_DIR="$ROOT/release"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$NAME"
# The bundle itself (binary + _internal) at the folder root.
cp -a "$BUNDLE/." "$STAGE/$NAME/"
# The operator docs an installer/upgrader needs, next to the binary.
cp docs/deployment/LOCAL.md docs/deployment/UPGRADE.md "$STAGE/$NAME/"

mkdir -p "$RELEASE_DIR"
ARCHIVE="$RELEASE_DIR/$NAME.tar.gz"
rm -f "$ARCHIVE" "$ARCHIVE.sha256"
tar -czf "$ARCHIVE" -C "$STAGE" "$NAME"
# Standard sha256sum format with the bare file name, so a recipient can
# run `sha256sum -c` from inside release/ (or wherever the pair landed).
(cd "$RELEASE_DIR" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")

echo "Release artifact: $ARCHIVE ($(stat -c %s "$ARCHIVE") bytes)"
echo "Checksum file:    $ARCHIVE.sha256"
echo "Verify with:      (cd release && sha256sum -c $NAME.tar.gz.sha256)"
