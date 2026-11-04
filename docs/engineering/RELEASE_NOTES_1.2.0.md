# Accountix 1.2.0 — Release Notes

Released: 2026-11-04. Follows 1.1.0 with Sprint 31: barcode/QR
scanning in invoicing, a guided-tour activation fix, and a
bidirectional localization closure. Version source of truth:
`backend/config/version.py` (`__version__ = "1.2.0"`).

## What's new since 1.1.0

- **Barcode / QR scanning while invoicing (ADR-060)** — the sales
  and purchase invoice forms gain a scan field: type or scan a
  product barcode (or SKU) and the product is added as a line, or
  its quantity incremented if already present — point-of-sale
  behavior, designed so USB scanner guns (which type the code and
  press Enter) work with no configuration. A camera button scans
  with the device camera (native browser barcode detection, with a
  vendored QR decoder as fallback), and **phone pairing** lets a
  phone act as the scanner: the form shows a short-lived pairing
  link/QR (10 minutes, token stored only as a hash, revocable),
  codes scanned on the phone are resolved inside the same company
  and added to the form on the desktop.
- **Guided tours actually activate (ADR-059)** — a CSS cascade bug
  (the global button rule defeated the browser's `[hidden]` rule)
  made the «راهنمای صفحه» button visible on every page, including
  pages without a tour, where it was a dead control. Fixed, and a
  permanent DOM-level (jsdom) test now clicks through the tours in
  both languages so this class of failure is caught automatically.
- **Localization, both directions (ADR-058)** — an English-mode
  crawl now complements the Persian one (both are permanent
  regression tests over 64 pages and 10 POST flows); the remaining
  display paths that bypassed translated labels were fixed
  (journal source types, stock document labels, cheque direction,
  boolean rendering). For source checkouts, `scripts/dev_run.sh`
  is the one-command startup (compiles translation catalogs, runs
  migrations, serves), and a new system check (`accountix.W001`)
  warns at startup when compiled catalogs are missing or stale —
  the state that used to make one language silently fall back to
  the other. Note: the packaged artifact always ships compiled
  catalogs and is unaffected by that class of problem.

## Release artifact (Linux)

- File: `accountix-1.2.0-linux.tar.gz` — 30,463,403 bytes
- SHA-256: `42f2b63f75302ac79d85c50fa84406194a497e1b25754789ce759fe47600086b`
- Produced by `scripts/build_linux.sh` + `scripts/package_release.sh`
  (ADR-054); checksum verified with `sha256sum -c`, and the binary
  extracted from the archive itself passed a smoke run: first-run
  setup, login, a dashboard rendering version 1.2.0 with the
  guided-tour payload, and the scan assets served.

## Verification summary

- Test suite: **500 passed, 3 skipped** (up from 476 at 1.1.0),
  including the new bilingual crawls, the DOM-level tour harness
  (30 checks), the scan/pairing server tests (14), and a jsdom
  scan harness (20 checks).
- **Upgrade from 1.1.0:** this release adds one database migration
  (`core 0001`, the scan-session tables). The launcher takes its
  usual pre-migration backup before applying it, so an existing
  1.1.0 data directory upgrades in place; source checkouts should
  use `scripts/dev_run.sh`, which migrates automatically.

## Known limitations

Unchanged platform notes from 1.1.0 — see `RELEASE_NOTES_1.1.0.md`.
In particular: the Windows bundle remains **NOT VERIFIED**, and
camera scanning requires a secure context (localhost or HTTPS) —
a browser platform rule; over plain-HTTP LAN access, scanner guns
and typed codes still work, and the phone page accepts manual
entry. Real-camera decoding was verified with the native detector
path in the DOM harness; the vendored QR decoder's live-video loop
has not been exercised on physical camera hardware.
