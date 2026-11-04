# Current State — Repository Assessment (Phase 0)

Date: 2026-11-02 (last updated Sprint 11, 2026-11-03). Assessor: Muse development coordinator (subagent).
Repository: `zeroexlive/Accountix` (private, "Accountant software").

## 1. Evidence for the starting point (verified, not assumed)

The master prompt warns not to assume the repository is empty. It was
checked through the GitHub connector before any code was written:

| Check (2026-11-02, parent session, re-verified by this agent) | Result |
|---|---|
| `github status` | `auth_status: connected`, user `zeroexlive` (id 84627588) |
| `search_repositories` for `repo:zeroexlive/Accountix` | 1 repo, id 1443168275, private, created 2026-11-02T15:55:17Z, default branch `main` |
| `get_file_contents` (root) | Error: `409 Git Repository is empty` |
| `list_commits` | Error: `409 Git Repository is empty` |
| `list_issues` | 0 issues |

Conclusion: there were **no files, branches with history, models, migrations,
tests, docs, workflows, or frontend/launcher code to inspect** — sections of
the Phase 0 audit that require existing code are therefore "none present",
not "reviewed and clean".

## 2. Current project architecture (after Sprint 01, this commit)

Modular monolith, single Django project under `backend/`:

- `config/settings/` split: `base`, `local`, `test`, `production`.
  Secrets from environment only; SQLite default; PostgreSQL when
  `DATABASE_URL` is a postgres URL (hand-rolled parser, no extra dep).
- Installed apps: `core` (UUID/timestamp base model, company-access helpers,
  dashboard, health endpoint), `users` (custom user, UUID pk, defined before
  first migration), `organizations` (Company, Branch, CompanyMembership,
  FiscalYear, FiscalPeriod), `accounting` (Account only), `audit`
  (AuditEvent + `record_event` helper).
- Update (Sprint 02/03): `accounting` also carries the journal engine;
  `catalog` (Unit, ProductCategory, Product, ProductUnitConversion) and
  `inventory` (Warehouse, StockDocument/Line, StockMovement,
  StockDocumentReversal) are installed since Sprint 03.
- Update (Sprint 04): `parties` (Party, PartyContact, PartyAddress) and
  `purchases` (PurchaseOrder/Line, PurchaseInvoice/Line, PurchaseReturn/
  Line) are installed; `JournalLine` gained a nullable party tag for
  subledgers (ADR-015).
- Update (Sprint 05): `sales` (SalesQuotation/Line, SalesInvoice/Line,
  SalesReturn/Line) is installed; sales posting issues stock at MWAC and
  posts revenue + COGS entries (ADR-020), returns restore at the original
  COGS cost (ADR-021). The internal MVP purchase-to-sale workflow passes
  end-to-end (see `SPRINT_05_REPORT.md`).
- Update (Sprint 06): `treasury` (TreasuryAccount, Payment,
  PaymentAllocation, Cheque) is installed; receipts/payments post
  party-tagged journals, allocations are the only writer of invoice
  `payment_status` (ADR-024), and the cheque register implements the
  in-hand/clearing/bounce model (ADR-026).
- Update (Sprint 07): `inventory` gained `InventoryCount`/`InventoryCountLine`
  (snapshot + warehouse-freeze counting, ADR-027); purchase and sales
  returns are now reversible; `accounting` gained opening balances
  (ADR-029), fiscal period/year closing with reopen-via-reversal
  (ADR-028), and derived income statement + balance sheet (ADR-030)
  with read-only Persian RTL pages for both statements and counts.
- Update (Sprint 08): `reporting` is installed as a model-free
  presentation layer (ADR-031): the core dashboard renders its
  aggregation service, list pages gained GET filters + pagination,
  CSV/XLSX exports landed under `/reports/exports/`, and invoices and
  party statements gained print templates (browser print-to-PDF is the
  PDF path, ADR-032).
- Update (Sprint 09): standalone desktop mode is implemented —
  `config.settings.standalone` + `config/paths.py` (per-user data
  directory, generated secret key), `backend/serve.py` (Waitress on
  127.0.0.1), the cross-platform launcher with backup-gated migrations
  (ADR-033/034), `backup_db`/`restore_db` management commands
  (ADR-035), and a PyInstaller spec + Linux/Windows build scripts.
  The Linux bundle was built and smoke-run for real (fresh launch,
  second-launch backup, clean SIGINT shutdown); the Windows bundle is
  written but untested on Windows.
- Update (Sprint 10): production hardening + the release gate are
  done — see `SPRINT_10_REPORT.md` and `RELEASE_READINESS.md`
  (verdict: **Ready with documented limitations**). The full suite
  now runs green on PostgreSQL 16.2 as well as SQLite, and on Python
  3.13.18 as well as 3.12.3 (202 passed on SQLite / 205 on PG).
  Threaded concurrency tests found and fixed a critical stock
  overselling race and a journal-idempotency race (ADR-037); mypy is
  a clean gate; password validators are configured; DRF is on
  3.18.3; the PG `pg_dump` backup path executed for the first time.
  Headline remaining limitation: the web UI is read-only for
  business documents (setup forms + admin only), Windows is still
  unverified, and there is no login rate limiting.
- Update (Sprint 11): the screen UI was rebuilt on design system v2
  (ADR-038) after the owner's "too dry and soulless" feedback — see
  `SPRINT_11_REPORT.md`. Sidebar shell (RTL-mirrored), topbar, KPI
  cards with previous-period delta badges, a pure-CSS revenue vs
  expenses bar chart per fiscal period, a performance panel of
  derived shares, status pills and a centered login card. Two new
  derived helpers in the reporting app (`period_series`, KPI deltas)
  are pinned equal to `income_statement` by tests; no business logic
  changed. Print output is untouched.
- Update (Sprint 12): the data-entry UI is done — see
  `SPRINT_12_REPORT.md` and ADR-039. The web UI is no longer
  read-only: parties, catalog (products/units/categories/warehouses),
  purchase and sales invoices and returns, treasury accounts,
  payments, allocations, cheque actions (deposit/clear/bounce/
  return) and manual journal entries are all created, posted and
  reversed from the UI, exclusively through the existing services
  (per-document GL account pickers, ADR-011; `payment_status` still
  only via the treasury recompute, ADR-024). Two thin accounting
  service functions (`create_journal_draft` / `post_journal_draft`)
  were the only service additions. Suite: 258 passed + 3 skipped on
  SQLite, mypy clean, no model changes. This closes limitation #1 of
  `RELEASE_READINESS.md`; that Sprint 10 document keeps its verdict
  as written — the limitation it records is now historical (the
  remaining readiness items are unchanged: PG restore drill and
  Windows bundle still NOT VERIFIED, no login rate limiting).
- Update (Sprint 13): data entry is complete and dates display in
  Jalali — see `SPRINT_13_REPORT.md`, ADR-039 patterns and ADR-040.
  The three Sprint 07 workflows that still had read-only pages now
  have UI: fiscal period closing (preview with the period's
  income-statement totals + retained-earnings picker →
  `close_fiscal_period`), reopening via `reopen_fiscal_period` (the
  service reverses the closing entry; the UI never flips a status),
  whole-year closing via `close_fiscal_year`, opening balances via
  `post_opening_balance` (one entry per fiscal year; the page links
  to the existing entry instead of offering a duplicate), and stock
  counts end to end (create snapshots all stockable products →
  counted quantities edited on the count page via the one new
  service `update_inventory_count_lines` → post with optional GL
  variance booking; the ADR-027 freeze rejection surfaces verbatim,
  with snapshot vs live quantities side by side). Dates: every
  displayed date renders Jalali (`YYYY/MM/DD`, Latin digits) through
  the `jalali` template filter in `apps/core/templatetags` backed by
  the pinned `jdatetime` dependency; storage, services and all form
  inputs stay Gregorian, and filter date inputs are labelled
  «(میلادی)». No page remains read-only except the statement/report
  pages themselves (filters + exports, by design). Suite: 283 passed
  + 3 skipped on SQLite, mypy clean, no model changes.
- Update (Sprint 14): bank reconciliation and stock document forms —
  see `SPRINT_14_REPORT.md` and ADR-041. Reconciliation is defined at
  the GL level (a book movement is a posted journal line on the bank
  treasury account's GL account, which covers bank payments and
  cheque clearings — and only flows that actually touch the bank GL);
  statements enter manually or by CSV import with per-row error
  reporting, auto-match links only unambiguous exact matches,
  matching is link-only (OneToOne to the journal line), the summary
  uses difference = book − (stated closing − unmatched statement
  net), and completion is locked until the difference is exactly
  zero with no unmatched line. Stock documents (receipt / issue /
  transfer / adjustment) now have create → draft → post/reverse UI
  with the ADR-013 GL opt-in, including the «موجودی اول دوره»
  purpose that stamps the Sprint 07 `opening_stock` receipt; the
  opening-balance page's opening-stock guidance links to the new
  form. This sprint HAS a migration
  (`treasury/0002_bankstatement_bankstatementline`). Suite: 298
  passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 15): cheque books + statement chaining prefill —
  see `SPRINT_15_REPORT.md` and ADR-042. A ChequeBook belongs to
  one BANK treasury account and generates its ChequeLeaf rows in
  one transaction with account-level number uniqueness (overlapping
  ranges impossible by DB constraint); an issued-cheque payment
  may name a leaf and consumes it inside `create_payment` (number
  taken from the leaf, conflicting entry rejected); bounce and
  payment reversal never resurrect a used leaf; void is
  UNUSED → VOID only; counts are derived by annotation. Books are
  opt-in — the no-leaf payment path is unchanged. The statement
  create form now prefills start date + opening balance from the
  account's latest COMPLETED statement (`?account=`), always
  editable. With this, the Sprint 06 follow-ups are ALL closed
  (bank reconciliation in Sprint 14, cheque books here). This
  sprint HAS a migration (`treasury/0003_chequebook_chequeleaf`).
  Suite: 318 passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 16): login rate limiting — see
  `SPRINT_16_REPORT.md` and ADR-043. `django-axes` 9.0.0 now
  throttles `/login/` in every settings profile: 5 failed attempts
  for one (username, IP) combination lock that combination out for
  a 1-hour cooloff (env-overridable), correct passwords are refused
  during the cooloff, a success resets the counter, and the lockout
  response is a Persian auth-card page with HTTP 403. Client IPs
  come from `REMOTE_ADDR` only (django-ipware deliberately not
  installed, so `X-Forwarded-For` is never trusted; proxied
  deployments opt in via the documented ipware settings). This
  closes release gate #20 of `RELEASE_READINESS.md`; that Sprint 10
  document keeps its table as written — the gap it records is now
  historical (remaining readiness items: PG restore drill and
  Windows bundle still NOT VERIFIED). Axes ships its own migrations
  (package tables only; no project model changes). Suite: 326
  passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 17): the PostgreSQL restore drill — see
  `SPRINT_17_REPORT.md`. On an embedded PostgreSQL 16.2 staging
  instance (the Sprint 10 `pgserver` route), a database seeded
  through the app's own services (posted purchase + sales invoices,
  an allocated receipt settling the sale, an issued cheque consuming
  cheque-book leaf 1001, a posted manual journal, one failed login
  so the axes tables carry rows) was backed up with `backup_db`
  (258,443-byte custom-format archive, 546 TOC entries) and restored
  with the ADR-035 operational procedure into a fresh empty
  database: `pg_restore --clean --if-exists` exited 0 with empty
  stderr. The restored database's fingerprint was **identical** to
  the source (all 58 table row counts — 420 rows — trial balance
  4275.00/4275.00 balanced, stock 6 units / 600.00 at MWAC 100,
  sale PAID, purchase PARTIALLY_PAID, leaf 1001 USED), `check`
  passed, a real login succeeded, dashboard + invoice pages
  returned 200, and new postings/axes rows wrote cleanly (sequences
  sane). Release gate #15 moves from NOT VERIFIED to **VERIFIED**
  (recorded here; `RELEASE_READINESS.md` keeps its Sprint 10
  table). The drill also exposed that the restore procedure had
  never actually been written down — PRODUCTION.md claimed
  "documented-but-unrun" but contained no procedure; it now carries
  the drill-verified steps. One code fix: `backup_db`'s default
  PostgreSQL filename ended in `.sql` although the content is a
  binary custom-format archive — now `.dump`, pinned by a test.
  Suite: 327 passed + 3 skipped on SQLite, mypy clean. Remaining
  NOT VERIFIED release item: the Windows bundle only.
- Update (Sprint 18): CAMT.053 + OFX statement import — see
  `SPRINT_18_REPORT.md` and ADR-044. The Sprint 14 importer is now
  one pipeline with many parsers (`treasury/statement_files.py`):
  CSV (byte-identical behaviour; Sprint 14 tests untouched),
  CAMT.053 (stdlib XML, namespace-agnostic, one statement per
  file) and OFX 1.x/2.x (a tolerant hand parser — `ofxparse` was
  evaluated and rejected: it UTC-shifts posting dates and aborts
  the whole file on one bad transaction). Formats are detected by
  content, never by extension; rows from every format go through
  the same validation, with rejected rows reported by physical
  line (CSV) or transaction index (XML formats). Files also yield
  header metadata: the create page has a create-from-file flow
  (upload → editable prefilled header — chaining suggestion first,
  file metadata over it — → create + import in one transaction
  with the totals identity opening + Σ lines == closing enforced
  at save), and the detail-page import accepts all formats for
  lines. OFX carries no opening balance (chaining/user supplies
  it, as with CSV). No migration, no new dependency. Suite: 346
  passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 19): i18n groundwork — see `SPRINT_19_REPORT.md`
  and ADR-045. The gettext pipeline is real now: template msgids
  are the Persian literals (fa catalog msgstrs empty by design —
  fallback renders the msgid, i.e. Persian, so the default UI is
  byte-identical), `locale/en` carries English translations for
  the wrapped set (103 strings, 100%), the language rides in
  Django's cookie via the stock `set_language` view (no URL
  prefixes), and `base.html` emits `lang`/`dir` from the active
  language (en → `en`/`ltr`; the CSS needed only two
  logical-property conversions). Wrapped scope is the **chrome
  only**: base shell + all nav labels, login, lockout, and the
  dashboard's static labels. Business pages are deliberately
  still unwrapped Persian in both modes — a wrapping sweep is
  the named follow-up. The `jalali` filter branches on language
  (fa → Jalali; otherwise Gregorian ISO). Catalogs are committed
  as `.po` only; `.mo` is a gitignored artifact compiled by the
  launcher (best effort), the bundle build scripts (hard step),
  or the developer (`compilemessages`; needs the gettext tools).
  Suite: 354 passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 20): the wrapping sweep is done — see
  `SPRINT_20_REPORT.md` and ADR-046. Every in-scope template
  (all business pages; print templates stay Persian per
  ADR-045), form label, view flash message and the dashboard
  performance labels are wrapped and translated: 1032 msgids,
  en 1032/1032, fa msgstrs empty by design. Two source-language
  facts now recorded: service `ValidationError` texts and model
  choice labels are English-source in this codebase — both are
  wrapped (`gettext_lazy`, named placeholders) with byte-identical
  rendering in both modes, and the choice labels produce **no
  migrations** (the serializer evaluates lazy proxies by value;
  verified with `makemigrations --check`). English mode is
  crawl-tested per app (labels present, Persian originals
  absent) plus English form-error and flash rendering.
  Suite: 363 passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 21): the English-source vocabulary is now
  Persian in the default UI — see `SPRINT_21_REPORT.md` and
  ADR-047 (Jason's product decision). The 339 English-source
  msgids (all service `ValidationError` texts + all model choice
  labels + 3 format patterns) carry Persian translations in
  `fa.po`; the 693 Persian-source msgids keep empty fa msgstrs
  (ADR-045 fallback). No source string changed, `en.po` is
  byte-untouched, no migration. Without a compiled `fa.mo` those
  339 entries fall back to English (the pre-Sprint-21 rendering),
  so `compilemessages` is now required for both languages on a
  dev checkout; the suite self-compiles via a session fixture in
  the root `conftest.py` (which also clears Django's translation
  caches — see ADR-047 for the spurious-pass trap it closes).
  29 test assertions in 7 files migrated to the Persian strings.
  Suite: 364 passed + 3 skipped on SQLite, mypy clean.
- Update (Sprint 22): the LTR design pass is done — see
  `SPRINT_22_REPORT.md` and ADR-048. A scripted census found
  zero physical direction declarations left in the stylesheet
  or templates (Sprint 19 had taken the last conversions); the
  sprint added the English design layer under `html[lang="en"]`
  / `[dir="ltr"]` selectors only (Latin-first font stack,
  tabular English display figures, the `.flip-rtl`
  directional-icon mechanism — the audit found no current icon
  qualifying) and activated the numeric rule: figure columns
  across 32 templates now carry the `num` hook (inline-end
  alignment + tabular numerals in both modes), which in Persian
  moves figure columns to the left edge of their cells — the
  sprint's one deliberate fa visual change, recorded in
  ADR-048. Catalogs provably untouched (makemessages md5
  fixpoint). **Post-report correction (Jason's decision,
  2026-11-03):** the numeric alignment was reverted to
  inline-start — Persian figures are right-aligned again as
  before Sprint 22, English figures left-aligned; the `num`
  hook coverage stands (ADR-048 addendum). Suite: 367 passed + 3 skipped on SQLite, mypy
  clean.
- Update (Sprint 23): the PyInstaller Linux bundle is rebuilt and
  current — see `SPRINT_23_REPORT.md`. The rebuild census caught a
  real defect the Sprint 09 spec would have shipped broken: the
  frozen PYZ contained `axes` without its migrations, middleware or
  backend (all referenced by string/by name since Sprint 16); the
  spec now collects `axes` submodules, and the frozen smoke proves
  the whole current app — 48 migrations applied by the bundle
  itself (axes 0001–0010, treasury/0003), real login, an axes
  access-attempt row after a failed login, Jalali rendering, all
  feature pages 200, and a fully English UI from the bundled .mo
  catalogs. Bundle: 116 MB in `dist/accountix/` (build output,
  never synced). One release-relevant finding: **the bundle alone
  cannot create its first user** (no management entry point; the
  documented path is a source checkout's `createsuperuser` against
  the data dir) — a Sprint 24 candidate. **Update (Sprint 24):
  that gap is closed** — a zero-user install redirects `/login/`
  to a one-time `/setup/` page (admin + first company in one
  transaction, kill switch `ACCOUNTIX_FIRST_RUN_SETUP`), the
  launcher takes `accountix manage <args...>` passthrough
  commands, and the rebuilt bundle's smoke ran the whole
  recipient journey bundle-only (ADR-049). The Windows bundle
  remains the only NOT VERIFIED release-gate item.
- Update (Sprint 25): role-permission enforcement is live —
  see `SPRINT_25_REPORT.md` and ADR-050. `CompanyMembership`
  roles (unused since Sprint 01) now gate every mutating
  endpoint by tier: READ for all members, OPERATE for every
  role except VIEWER, ADMINISTER (fiscal close/reopen, year
  close, fiscal-year creation, opening balances, chart of
  accounts, treasury accounts) for OWNER/ADMIN, GOVERN
  (membership management) reserved for OWNER — no members UI
  exists yet, so GOVERN gates nothing and assignment stays
  with the Django admin. Enforcement is one helper home
  (`apps/core/access.py`), a Persian 403 page for under-roled
  members, non-members still 404 exactly as before, and
  in-service assertions in the closing/opening-balance
  services. No model changes; no fixture changes were needed
  (every UI test builder already modelled the OWNER). The
  PyInstaller bundle is now one sprint behind the code again
  (Sprint 24 build); the Windows bundle remains the only
  NOT VERIFIED release-gate item.
- Update (Sprint 26): the GOVERN tier is real — a per-company
  members UI (ADR-051) lists the roster and lets the OWNER
  attach an existing user by username or create a new user
  inline (full password validators, Sprint 24 pattern; no
  email invites — the product is offline-first), change roles
  (effective on the member's next request), and deactivate /
  reactivate memberships. Deactivation is the removal path —
  no hard delete — and cuts access immediately; a service-layer
  guard refuses to demote or deactivate the company's last
  active OWNER. All mutations are organizations services that
  re-assert GOVERN themselves; Django-admin assignment remains
  available as the operator's tool. No model changes, no
  migration. The PyInstaller bundle was rebuilt in the same
  sprint and its frozen smoke ran the whole story bundle-only
  (setup → members page → create a VIEWER inline → that user
  logs in, reads, and is 403-denied on an OPERATE POST), so the
  bundle is current through Sprint 26; the Windows bundle
  remains the only NOT VERIFIED release-gate item.
- Update (Sprint 27): the self-service account surface is real
  (ADR-052) — `/profile/` + `/profile/password/` in the users app,
  self-only by construction (no user id in any URL), linked from
  the shell's identity area for every signed-in user. First/last
  name and email are editable (email keys nothing — auth + axes
  key on the username); the username is read-only and not a form
  field, so it cannot be smuggled into a change. Password change
  is Django's built-in view: current password required, full
  validators, this session kept alive via
  `update_session_auth_hash`; failed attempts provably do not
  feed the axes lockout (the form uses `check_password`, never
  `authenticate()`). A two-level VIEWER crawl audit of the
  dashboard + shell found and fixed two visible-but-dead controls
  Sprint 25 missed (product-list per-row edit link, party-detail
  edit button — both now hidden per role). The product version
  has one home, `config/version.py` = "1.0.0", rendered in the
  sidebar footer + login page; `docs/engineering/RELEASE_STATUS.md`
  now carries the current gate picture (RELEASE_READINESS.md
  untouched, historical). No model changes, no migration. The
  bundle was rebuilt and its frozen smoke ran the whole account
  journey bundle-only (setup → profile rename → password change →
  old password rejected, new password in), so the bundle is
  current through Sprint 27; the Windows bundle remains the only
  NOT VERIFIED release-gate item.
- Update (Sprint 28): design system v3 "Bento" is live (ADR-053),
  commissioned after the owner judged DS v2 still "dry and
  soulless" — self-hosted Inter + Vazirmatn webfonts (woff2,
  400/500/700/800, one combined per-character-fallback stack for
  both locales), a self-hosted Lucide SVG sprite replacing every
  hand-drawn inline icon (36 symbols, generated by
  `scripts/build_icon_sprite.py`), bento tokens (24px tiles,
  floating sidebar + topbar, tinted icon chips, CSS-only canvas
  tints) and a true bento dashboard (KPI tiles, spanning chart
  tile, performance tile, a quick-actions tile whose links all
  work and which follows the OPERATE tier, mini stat tiles) —
  every figure still derived from the Sprint 11 helpers, whose
  numeric assertions pass unchanged. Zero external assets is now
  a pinned test, not a convention. No model changes, no
  migration; print templates untouched. The bundle was rebuilt
  (fonts + sprite inside; frozen smoke ran setup → bento
  dashboard in fa and en, all assets 200 from the frozen server,
  zero external URLs), so the bundle is current through
  Sprint 28; the Windows bundle remains the only NOT VERIFIED
  release-gate item.
- Update (Sprint 29): the release is packaged and the in-place
  upgrade is verified — see `SPRINT_29_REPORT.md` and ADR-054.
  `scripts/package_release.sh` turns the bundle into
  `release/accountix-1.0.0-linux.tar.gz` (+ a `.sha256` sidecar;
  the version is parsed from `config/version.py` at package time,
  never hardcoded; the archive's single top-level folder holds
  the bundle plus `LOCAL.md`/`UPGRADE.md`); `build_windows.bat`
  mirrors the naming for `accountix-<VERSION>-windows.zip`
  (written-only, NOT VERIFIED like the rest of the Windows
  route). The packaged artifact was smoked from a clean
  extraction (fresh data dir: setup → dashboard with the 1.0.0
  stamp → fonts from the frozen server), and the ADR-036 upgrade
  story was proven on a data directory populated by the packaged
  binary and then rolled back one migration (`treasury.0003`):
  the launch wrote the verified pre-migration backup first,
  applied 0003, and a Sprint 17-style fingerprint of the old data
  (trial balance 3775.00 = 3775.00, sale PAID, stock 6/600,
  memberships with roles) was identical after the upgrade;
  pre-upgrade admin + member logins still work and the
  cheque-books page loads; a garbage-DB data dir is refused at
  the backup gate with the data untouched. No application code
  changed; the suite is unchanged at 455 passed + 3 skipped.
  The Windows bundle remains the only NOT VERIFIED release-gate
  item.
- Update (Sprint 30): three workstreams on top of the 1.0.0
  release (version unchanged) — see `SPRINT_30_REPORT.md` and
  ADR-055/056/057. (A) The fa UI leaks behind Jason's bug report
  are closed: a full fa-mode crawl over a populated world found
  multi-line `{# #}` comments rendering as text, untranslated
  auto-generated form labels, and raw enum codes bypassing the
  translated choice labels (all fixed), plus 25 f-string service
  strings converted to gettext templates so NEW records store
  Persian descriptions under fa (history is never rewritten);
  framework strings proven clean against Django's bundled fa
  catalog. The crawl is now a permanent regression test. (B) The
  dashboard chart is a server-rendered SVG area/line chart and
  the performance rows carry SVG rings — both from the same
  pinned derived data — with all motion CSS-only inside
  `@media (prefers-reduced-motion: no-preference)`. (C) A
  self-hosted guided-tour engine (`static/js/tour.js`) with
  server-rendered bilingual steps covers 13 pages / 56 steps;
  the topbar «راهنمای صفحه» button ships hidden and is revealed
  by the engine only where a tour exists. Catalogs: 1,212
  msgids per language. Suite: 476 passed + 3 skipped. The Linux
  bundle was rebuilt so `dist/` carries Sprint 30 (the released
  1.0.0 artifact is untouched). The Windows bundle remains the
  only NOT VERIFIED release-gate item.
- Update (Sprint 31): three workstreams on top of the 1.1.0
  release (version unchanged, artifact NOT re-packaged) — see
  `SPRINT_31_REPORT.md` and ADR-058/059/060. (A) i18n closed in
  BOTH directions: a permanent en-mode crawl twin (same world,
  same 64 GET + 10 POST flows) passes clean, the fa crawl gained
  a strict visible-text token rule, and the real leaks were
  render-layer raw codes (journal source types via a new
  translated label map, `StockDocument.__str__`, cheque
  direction, a True/False blocktrans). The clone footgun behind
  most of the report — `runserver` never compiles catalogs, so
  an uncompiled clone falls back to source strings in BOTH
  languages — is killed by `scripts/dev_run.sh` (the documented
  one-command startup), a Django system check `accountix.W001`
  that warns on missing/stale `.mo`, and DEVELOPMENT.md making
  dev_run.sh the documented path. Catalogs: 1,249 msgids per
  language, en 0 empty, fa 0 real gaps, 0 fuzzy. (B) The tour
  "cannot activate" bug was a CSS cascade defect: the global
  `button,.btn{display:inline-block}` rule defeated the UA
  `[hidden]{display:none}`, so the tour button rendered visible
  (and dead) on every page; fixed with
  `[hidden]{display:none !important}` and guarded permanently by
  a jsdom DOM harness (`scripts/tour_dom_check/`) that executes
  the real tour.js on real rendered pages (fa+en) — the engine
  itself was proven sound. (C) Barcode/QR scanning in invoicing
  (ADR-060): company-scoped OPERATE-gated lookup (barcode then
  SKU), a scan widget on sales + purchase invoice create
  (scanner-gun Enter, camera via BarcodeDetector → vendored
  jsQR fallback, POS quantity increment), and phone pairing
  (hashed-token sessions, 10-min expiry, phone-side product
  resolution, consume-once polling) with vendored
  qrcode-generator for the pairing QR; jsdom coverage drives
  the real scan.js end to end. Suite: 500 passed + 3 skipped.
  The Linux bundle was rebuilt so `dist/` carries Sprint 31
  and frozen-smoked (setup → dashboard 1.1.0 + tour payload,
  scan assets 200, pairing session created from the bundle).
  The Windows bundle remains the only NOT VERIFIED gate.
- UI: Django templates, Persian-first RTL layout, hand-written CSS design
  system v2 in `backend/static/css/app.css`. **Honest limitation:** Tailwind is
  not integrated yet, and HTMX/Alpine are not loaded (no vendored copies; a
  CDN would break the offline-first claim). Interactivity is server-rendered.
  Since Sprint 12 the web UI is fully writable for business documents
  (data entry through the service layer only — see ADR-039), and since
  Sprint 13 also for opening balances, stock counts and fiscal
  closing. Displayed dates are Jalali (ADR-040); inputs stay
  Gregorian. Only the statement/report pages are read-only views
  (they take filters and produce exports, by design).

## 3. Existing functionality (implemented + tested in Sprint 01)

Login/logout (session auth), login-required dashboard, company
list/create/detail with membership-scoped querysets (creating a company
grants the creator an OWNER membership), fiscal year list/create, chart of
accounts list/create, `/health/` endpoint, Django admin registrations.

## 4. Missing functionality (planned — does NOT exist yet)

_Update 2026-11-02 (Sprint 02): journal entries/lines, posting & reversal
services, trial balance and general ledger are now implemented and tested
(42 tests total) — see `SPRINT_02_REPORT.md`. The paragraph below is the
remaining gap list._

_Update 2026-11-02 (Sprint 03): catalog (products/units/conversions) and
the inventory ledger (warehouses, stock documents, MWAC movements,
derived balances, opt-in GL posting) are implemented and tested
(74 tests total) — see `SPRINT_03_REPORT.md`._

_Update 2026-11-02 (Sprint 04): parties and purchasing are implemented
and tested (99 tests total) — purchase invoices post into inventory and
(optionally) the GL, supplier balances are a journal-line subledger —
see `SPRINT_04_REPORT.md`. Additional purchase costs (landed-cost
allocation) are deferred (ADR-017); no payment recording exists yet, so
every posted invoice stays UNPAID until treasury._

Reporting/PDF/Excel exports, API endpoints (DRF is
installed but exposes nothing yet), desktop launcher (only directory
skeleton), backups, MkDocs/OpenAPI, CI workflow execution on GitHub
(a workflow file is included but has never run), Persian `.po` translations,
Jalali date display, toman/rial display conversion.

## 5. Technical debt

- TD-1: Fiscal validation lives in organizations; accounting will consume it
  in Sprint 02 — keep one source of truth, do not duplicate.
- TD-2: Split 0001/0002 migrations generated by cross-app dependencies are
  normal Django output but should be reviewed before any squash.
- TD-3: `is_postable` naming: prompt says "posting eligibility"; field kept
  as `is_postable`, documented in DECISIONS.md ADR-005.
- TD-4: ~~Python 3.13 unverified~~ — resolved in Sprint 10: the full
  suite passes on Python 3.13.18 (uv-installed) as well as 3.12.3.
  `requires-python = ">=3.12"` stands.
- TD-5: No `uv.lock`: `uv` is not installed on this machine; pip + venv was
  used and `pyproject.toml` declares all dependencies. Generate `uv.lock`
  when uv becomes available.
- TD-6: Audit events are only written when a service calls `record_event`;
  since Sprint 02/03 the journal and stock posting/reversal services do
  write them (`journal.posted/reversed`, `stock.posted/reversed`).

## 6. Security concerns

- No secrets in the repo; `.env` git-ignored; production settings refuse the
  dev secret key and force secure cookies/HSTS.
- Company isolation is enforced by membership-filtered querysets and tested
  (non-member detail view returns 404, list views leak nothing).
- Sprint 10 update: dependency scanning (pip-audit) and deploy checks
  were run and triaged (see RELEASE_READINESS.md gates 5–8, 17–20);
  password validators were found absent and are now configured.
- Not yet done: role-based permission checks beyond membership (roles exist
  as data only). **Login rate limiting** is done (Sprint 16, ADR-043:
  django-axes, (username, IP) lockout at 5 failures with a 1-hour
  cooloff) — release gate #20 is closed.

## 7. Database concerns

- Money: no monetary fields exist yet; when they land they must be
  `DecimalField` (rules in ACCOUNTING_RULES.md). No floats anywhere.
- SQLite vs PostgreSQL locking differences are noted in settings and rules;
  concurrency tests were **run for the first time in Sprint 10** against
  PostgreSQL 16.2 (embedded `pgserver` instance — this machine has no
  system PostgreSQL): two races failed pre-fix and were fixed (ADR-037).
  PostgreSQL restore (`pg_restore --clean --if-exists` into a fresh
  empty database, ADR-035) was executed and verified in the
  Sprint 17 staging drill: restored fingerprint identical to the
  source, app-level verification passed — release gate #15 is
  VERIFIED (see `SPRINT_17_REPORT.md`).
- All business models use UUID primary keys, explicit FKs, unique
  constraints per company (branch code, membership, account code).

## 8. Documentation gaps

This commit creates the required doc set, but deployment guides are brief
stubs, the user guide covers only getting started, and API docs do not exist
because there is no API yet. Docs deliberately label planned features as
planned.

## 9. Test coverage assessment

384 pytest tests passing on SQLite with 3 skipped (Sprint 01: 25 — authentication 5,
organizations/fiscal 11, accounting accounts 7, core/health/audit 2;
Sprint 02: +17 journal/posting/reversal/reporting; Sprint 03: +32
catalog/inventory tests; Sprint 04: +25 parties/purchasing tests;
Sprint 05: +16 sales tests including the §20.4 MVP end-to-end test;
Sprint 06: +20 treasury tests including a treasury end-to-end test that
settles the MVP chain with real payments, allocations and a cleared
cheque; Sprint 07: +30 counts, reversible returns, opening balances,
fiscal closing/reopening, statements and their read-only pages;
Sprint 08: +16 reporting/dashboard/filter/export/print tests;
Sprint 09: +15 standalone-settings, data-dir, launcher-logic, health
polling and backup/restore tests, including a subprocess round-trip of
the real management commands; Sprint 10: +9 tests (3 PostgreSQL
concurrency — they skip on SQLite — 5 password-validator/security
settings, 1 open-items query-count); Sprint 11: +12 dashboard-v2
tests (series equality, delta cases, performance percentages and
empty states, sidebar link integrity, print markers); Sprint 12:
+44 data-entry UI tests (golden-path buy→sell→pay E2E through the
forms, per-area UI flows, negative/permission paths); Sprint 13:
+25 (Jalali conversion pairs + rendered pages, closing/reopen via
UI, opening balances via UI, stock-count UI incl. the freeze
rejection and the draft-lines service); Sprint 14:
+15 (reconciliation services incl. the difference-identity scenario,
reconciliation UI, stock-document UI); Sprint 15:
+20 (cheque-book generation/collision/consumption/lifecycle,
chaining helper, cheque-book UI + prefill); Sprint 16:
+8 (login throttling: below-limit behaviour + reset-on-success,
lockout at the limit incl. correct-password refusal, cooloff
expiry, (username, IP) scoping, axes admin registration,
production/standalone settings wiring incl. env override); Sprint 17:
+1 (PG backup default filename `.dump` pin); Sprint 18:
+19 (statement-file parsers: CAMT.053/OFX golden rows + metadata,
per-transaction rejections, garbage refusals, generalized import
service, create-from-file totals identity + UI); Sprint 19:
+8 (i18n: default fa/RTL chrome, en switch + LTR rendering,
cookie persistence across login, switch back, jalali filter
language branches, untranslated-msgid fallback, production/
standalone i18n settings wiring); Sprint 20:
+9 (i18n sweep: English-mode crawl of list/detail/form pages for
every app, English service form error, English success/info
flashes); Sprint 21:
+1 (i18n: pinning test — an English-source service error and a
choice label render Persian under fa, English under en; the
sprint also migrated 29 existing assertions in 7 files to the new
Persian renderings, count-neutral); Sprint 22:
+3 (i18n LTR design: stylesheet ships the en font/tabular and
flip-rtl rules, numeric `num` hook live on a real page in both
en/LTR and fa/RTL); Sprint 23:
+0 (bundle rebuild + frozen smoke; the suite was the regression
net, count-neutral); Sprint 24:
+17 (first-run setup: zero-user login/root redirects, setup form
validation creating nothing, atomic admin+company+membership
creation, setup death after first user, kill switch, English
setup rendering; launcher manage passthrough: argv parsing,
dispatch, real `manage check` exit-code propagation); Sprint 25:
+24 (role matrix: tier pinning against the model choices, reads
for all 8 roles, viewer operate POSTs 403 with nothing persisted,
operate-tier administer denials, top-tier administer passes,
service-layer PermissionDenied assertions, non-member 404 on read
and write, per-company OWNER-of-A/VIEWER-of-B resolution, setup
admin unaffected, button-hiding and shell role-label checks);
Sprint 26:
+22 (members UI: GOVERN gating of page + actions for non-OWNER
members with nothing persisted, non-member 404, attach-existing
happy path + unknown-username / already-member / invalid-role
form errors, create-new happy path with a real login POST, weak
password rejected by the validators, duplicate username, role
change governing the member's very next request, last-owner
demote + deactivate refused with two-owner lift, deactivation
cutting access to 404 and reactivation restoring it,
cross-company membership id 404, service-layer GOVERN assertion
and guard); Sprint 27:
+16 (account surface: anonymous redirects to login, profile GET
shows current values with no username input, POST persists
name/email and the shell links render, username-smuggle POST is
a no-op, invalid email rejected, profile rename reflects on the
members roster, self-only by construction (a second user's data
never renders), VIEWER uses both pages; password change: wrong
current rejected + unchanged, weak new rejected by the
validators, success keeps the session while a real old-password
login fails and a real new-password login succeeds, six failed
changes do not trip the axes lockout; version stamp on the login
page + shell; VIEWER-audit fixes: product-list + party-detail
edit links hidden for VIEWER, shown for OWNER, server gates
unchanged); Sprint 28:
+9 (design system v3: the eight vendored woff2 files carry the
wOF2 magic and are the files the @font-face rules declare, the
combined "Inter","Vazirmatn" stack is the body font, every
template <use> reference resolves to a sprite symbol and every
sprite symbol is used, no inline SVG remains in any template,
zero external asset references across templates + app.css,
the bento dashboard renders its grids + sprite icons + the
five quick-action links for an OWNER and the same tiles without
quick actions for a VIEWER); Sprint 29:
+0 (packaging + upgrade-verification sprint, count-neutral; the
evidence is the artifact checksum/extraction smoke and the
upgrade fingerprint comparison, not new tests); Sprint 30:
+21 (the fa crawl becomes three permanent tests — GET crawl,
POST-error crawl, stored-description language contract; ten
chart/motion tests pinning SVG geometry against period_series,
donut arc sums, and the reduced-motion CSS scoping; eight tour
tests pinning payloads, anchors, the VIEWER skip contract and
the en payload; one Sprint 28 sprite test gains the scoped
chart exception and the zero-external scan grows to cover
tour.js; one Sprint 11 markup assertion moves from CSS bars to
the SVG chart, numerics untouched; one pre-existing test's raw
"POSTED" assertion becomes the translated label it now renders)
— see the sprint reports for exact
commands). Coverage tooling (pytest-cov) is configured as a dev
dependency but a coverage percentage was **not measured in Sprint 01** — do
not quote one. No integration/E2E/concurrency/security suites yet.

## 10. Recommended corrective actions & implementation priorities

1. ~~Sprint 02: accounting engine~~ — done. Sprint 03 (inventory) — done.
   Sprint 04 (purchasing + parties) — done. ~~Sprint 05 sales~~ — done
   (internal MVP reached). ~~Sprint 06 treasury~~ — done (payments,
   allocations, cheques; the only writer of `payment_status`).
   ~~Sprint 07 advanced inventory & accounting~~ — done (stock counting
   with snapshot + warehouse-freeze, reversible purchase/sales returns,
   opening balances, fiscal period/year closing with reopen-via-reversal,
   income statement + balance sheet with the result-line identity).
   ~~Sprint 08 reporting & UX~~ — done (derived dashboard, filters,
   CSV/XLSX exports, print templates). ~~Sprint 09 desktop packaging~~
   — done (standalone settings, launcher, backup/restore, Linux
   PyInstaller bundle built + smoke-run; Windows written-only).
   ~~Sprint 10 production hardening~~ — done (PostgreSQL suite +
   concurrency fixes, mypy gate, Python 3.13 verified, security
   review, RELEASE_READINESS.md verdict "Ready with documented
   limitations"). ~~Data-entry UI for business documents~~ — done
   (Sprints 12–13, including opening balances, stock counts, fiscal
   closing and Jalali display). ~~Bank reconciliation + stock
   document forms~~ — done (Sprint 14, ADR-041; the largest unbuilt
   treasury feature is closed). ~~Cheque books~~ — done (Sprint 15,
   ADR-042; with this, ALL Sprint 06 follow-ups are closed).
   ~~Login rate limiting~~ — done (Sprint 16, ADR-043; release
   gate #20 closed). ~~PG restore drill~~ — done (Sprint 17;
   release gate #15 VERIFIED, and the restore procedure is now
   actually written in PRODUCTION.md). ~~CAMT.053/OFX statement
   import~~ — done (Sprint 18, ADR-044). ~~i18n groundwork (.po
   translations)~~ — done (Sprint 19, ADR-045). ~~i18n wrapping
   sweep (English mode complete)~~ — done (Sprint 20, ADR-046).
   ~~Translating service/choice strings into Persian in fa.po~~
   — done (Sprint 21, ADR-047; Jason took the product decision —
   the default UI's status/error vocabulary is now Persian).
   ~~LTR design pass~~ — done (Sprint 22, ADR-048).
   Post-v1.0 candidates: Windows verification. ~~Rebuilding the
   PyInstaller bundle~~ — done (Sprint 23; bundle current through
   Sprint 22 + follow-up, frozen smoke green; new candidate from
   that sprint: a first-user bootstrap for bundle recipients).
   ~~First-user bootstrap for bundle recipients~~ — done
   (Sprint 24, ADR-049: first-run setup page + launcher manage
   passthrough; bundle rebuilt and the recipient journey
   smoke-proven bundle-only).
2. Run the included GitHub Actions workflow once the code is on GitHub;
   add Python 3.13 to the matrix.
3. Vendor Tailwind + HTMX/Alpine locally; remove the CSS stopgap gradually.
4. Generate `uv.lock`; add coverage measurement to CI.
5. ~~Add role permission checks when the first role-sensitive operation lands~~ — done (Sprint 25, ADR-050: tiered enforcement on every mutating endpoint; ~~the follow-up is a GOVERN-gated members UI with the last-OWNER guard~~ — done, Sprint 26, ADR-051). ~~Self-service profile + password change~~ — done (Sprint 27, ADR-052; current release picture in RELEASE_STATUS.md — the only open gate left is Windows bundle verification). ~~Versioned release artifact + in-place upgrade drill~~ — done (Sprint 29, ADR-054: `accountix-1.0.0-linux.tar.gz` + sha256, extraction-smoked; the ADR-036 upgrade from a one-migration-behind populated data dir is verified with an identical before/after fingerprint).
