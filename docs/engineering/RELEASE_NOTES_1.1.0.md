# Accountix 1.1.0 — Release Notes

Released: 2026-11-04. Follows 1.0.0 (same day) with the Sprint 30
feature and quality pass. Version source of truth:
`backend/config/version.py` (`__version__ = "1.1.0"`).

## What's new since 1.0.0

- **Guided tours (ADR-057)** — a «راهنمای صفحه» (page guide) button in
  the topbar of every page opens a step-by-step tour of that page:
  spotlight highlight, explanation card, step counter, keyboard
  navigation, in Persian and English. Thirteen pages carry tours
  (56 steps): dashboard, sales, purchases, payments, cheques, bank
  reconciliation, products, stock documents, financial statements,
  fiscal years, members, and profile. The engine is a small in-house
  vanilla-JS file — self-hosted like everything else, no library,
  no external requests.
- **SVG charts and motion (ADR-056)** — the dashboard chart tile is
  now a server-rendered SVG revenue/expense area chart plotted from
  the same `period_series` figures as before (geometry pinned by
  tests), and each performance share renders as its own progress
  ring. A restrained CSS motion pass (chart draw-in, tile entrance,
  hover transitions, 150–250 ms) runs only under
  `prefers-reduced-motion: no-preference`; reduced-motion users get
  a fully static interface.
- **Persian UI leak closure (ADR-055)** — a full crawl of the
  Persian UI (64 pages plus 10 POST flows, populated data) found and
  fixed every English sentence leaking into Persian pages. The
  largest root cause was subtle: multi-line `{# #}` template
  comments render as visible text in Django, and three templates
  leaked their (English) comments into every page. Also fixed:
  auto-generated English form labels, raw enum codes shown instead
  of their translated labels, raw `True`/`False` values, and 25
  service strings built outside gettext. The crawl is now a
  permanent regression test in the suite — a future English sentence
  in a Persian page fails CI.

## Release artifact (Linux)

- File: `accountix-1.1.0-linux.tar.gz` — 30,349,731 bytes
- SHA-256: `d5367412a62bb32fe1f4a977c5eeac91d189e10174a4678ea5c16aa223e3ea4e`
- Produced by `scripts/build_linux.sh` + `scripts/package_release.sh`
  (ADR-054); checksum verified with `sha256sum -c`, and the binary
  extracted from the archive itself passed a smoke run: first-run
  setup, login, and a dashboard rendering version 1.1.0 with the
  guided-tour payload present.

## Verification summary

- Test suite: **476 passed, 3 skipped** (up from 455 at 1.0.0).
- Upgrade from 1.0.0: no database migrations were added since
  1.0.0, and the launcher's backup-before-migrate path is unchanged
  — an existing 1.0.0 data directory opens directly under 1.1.0
  (the general in-place upgrade was verified end to end for 1.0.0,
  Sprint 29).

## Known limitations

Unchanged from 1.0.0 — see `RELEASE_NOTES_1.0.0.md`. In particular:
the Windows bundle remains **NOT VERIFIED** (no Windows machine in
the development environment), the eight woff2 font binaries are not
in the git remote (they ship inside the artifact; source clones
re-vendor them per `docs/engineering/DEVELOPMENT.md`), and
forgotten-password recovery is operator-only.
