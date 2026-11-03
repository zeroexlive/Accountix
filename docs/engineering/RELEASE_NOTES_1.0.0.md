# Accountix 1.0.0 — Release Notes

Released: 2026-11-04. First release. Version source of truth:
`backend/config/version.py` (`__version__ = "1.0.0"`).

## What Accountix is

Offline-first, double-entry accounting and inventory software for
Iranian businesses. Persian (RTL) UI by default with a full English
(LTR) localization; IRR amounts with an explicit rial/toman display
distinction; Jalali display dates over Gregorian stored dates.

## Included in 1.0.0

- **Accounting engine** — genuine double-entry journals with a
  DRAFT → VALIDATED → POSTED → REVERSED lifecycle, fiscal periods and
  years, period/year closing by atomic reversal, opening balances
  balanced by construction, trial balance and general ledger derived
  from posted lines only (Decimal everywhere).
- **Inventory** — append-only stock ledger, moving weighted average
  cost, negative-stock prevention, stock documents (receipt, issue,
  transfer, adjustment, opening stock) and inventory counts.
- **Purchasing and sales** — parties with subledgers, purchase/sales
  invoices and returns posting stock + GL atomically.
- **Treasury and Iranian cheques** — treasury accounts, payments and
  allocations, the full received-cheque lifecycle (in hand, deposited,
  cleared, bounced, returned), cheque books with leaf tracking, bank
  reconciliation at GL level, and statement import in CSV, CAMT.053
  and OFX formats.
- **Reporting** — dashboard, financial statements (income statement,
  balance sheet with the balance identity preserved), CSV/XLSX
  exports, print-to-PDF layouts.
- **Multi-company and access control** — strict per-company data
  isolation; eight membership roles with enforced tiers
  (READ / OPERATE / ADMINISTER / GOVERN, ADR-050); an OWNER-only
  members page with a last-owner guard (ADR-051); login rate limiting
  (django-axes); self-service profile and password change (ADR-052).
- **Design System v3 "Bento"** (ADR-053) — bento-grid dashboard,
  self-hosted Vazirmatn + Inter fonts and a Lucide icon sprite.
  **Zero external dependencies**: no CDN, no web fonts, no external
  requests of any kind (guarded by a permanent test).
- **Standalone desktop app** — launcher with single-instance check,
  automatic pre-migration backup, first-run setup (no command line
  needed to create the first user), and a `manage` passthrough for
  operators.

## Release artifact (Linux)

- File: `accountix-1.0.0-linux.tar.gz` — 30,287,244 bytes
- SHA-256:
  `222f5777de59252bbec073c2953e7dfe1f78a4ea9da0c574dd2da692399820e3`
- Produced by `scripts/build_linux.sh` + `scripts/package_release.sh`
  (ADR-054); checksum verified, and the binary extracted from the
  archive itself passed the full smoke run.

## Verification summary

- Test suite: **455 passed, 3 skipped** (SQLite), plus the Sprint 10
  PostgreSQL verification (205 passed, concurrency invariants).
- All 22 release gates closed or verified on the Linux route — see
  `RELEASE_STATUS.md` for the gate-by-gate record.
- **In-place upgrade verified** (Sprint 29): the packaged binary
  launched against a populated older data directory created its
  pre-migration backup, applied the pending migration, and left the
  data fingerprint byte-identical (trial balance, invoice states,
  stock, memberships).
- PostgreSQL backup/restore drill verified end to end (Sprint 17).

## Known limitations

- **Windows bundle: NOT VERIFIED.** The Windows build script and
  packaging exist and mirror the Linux route, but they have never
  been run on a Windows machine (none is available in the
  development environment). Treat the Windows artifact as unproven
  until the checklist in `RELEASE_STATUS.md` has been executed on
  Windows hardware.
- **Font binaries are not in the git remote.** The eight woff2 files
  cannot travel through the project's sync connector (UTF-8 snapshot
  limit). They ship inside the release artifact and the bundle; a
  source clone re-vendors them in two minutes following
  `docs/engineering/DEVELOPMENT.md` (versions and sha256 in
  `backend/static/THIRD_PARTY_NOTICES.md`). A clone without them
  degrades gracefully to the system font stack.
- **Forgotten-password recovery is operator-only** —
  `accountix manage changepassword`. The in-app password page covers
  signed-in users changing their own password.
- Membership administration beyond the members page (e.g. staff
  flags) remains a Django-admin/operator task by design.
