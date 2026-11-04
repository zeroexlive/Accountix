# Sprint 31 Report — Bidirectional i18n closure, tour activation fix, barcode/QR scanning

Date: 2026-11-04. Baseline: local HEAD `95522b6` ("Release 1.1.0"),
remote `02ff474`. Version stays **1.1.0** — no bump, and the
released artifact was **not** re-packaged.
ADRs: **058** (i18n + footgun), **059** (tour root cause),
**060** (scanning + pairing).

Suite: **500 passed + 3 skipped** (baseline 476 + 3; +24 new
tests, itemized below; no existing assertion weakened — the fa
crawl rule was *tightened*, §A.3).

---

## Workstream A — Bidirectional i18n closure (ADR-058)

### A.1 The census correction (read this first)

The pre-sprint suspicion was "~96 empty en msgstr". A proper
multiline-aware PO parse (entries whose msgstr spans lines begin
with `msgstr ""` and fool line-based counting) showed the
catalogs were **already complete** at sprint start:

| Catalog | Entries | Empty msgstr | Real gaps | Fuzzy |
|---|---|---|---|---|
| en.po (start) | 1,212 | **0** | — | 0 |
| fa.po (start) | 1,212 | 882 by design* | **0** | 0 |

\* fa.po leaves Persian-source msgids empty on purpose (ADR-046
fallback renders the Persian source). Real gaps = empty msgstr
on *Latin-source* msgids: zero.

So the leaks Jason saw were **not** catalog gaps. They were
(a) render paths that bypass gettext entirely (§A.3), and
(b) the uncompiled-catalog clone footgun (§A.4) — which, on an
uncompiled clone, breaks BOTH directions at once and matches
the report exactly.

### A.2 The en-mode crawl (new, permanent)

`test_i18n_fa_crawl.py`'s world builder was refactored into
`build_crawl_world(lang)` (fa behavior byte-identical) and a
twin test, `test_i18n_en_crawl.py`, walks the SAME populated
world as OWNER in en mode: the same 64 GET pages + 10 POST
error flows, rejecting Persian sentences/tokens in visible text
and in placeholder/title/aria-label/alt/submit attributes, plus
an Arabic-script scan of the tour JSON on 4 pages (dashboard,
sales list, profile, members). The only defended Arabic
allowlist entry is «فارسی» — the language switcher naming
Persian in its own script (endonym convention; see §D.1).
**Result: clean.** With fresh `.mo`, en mode renders no Persian.
The print templates stay Persian by design (ADR-045) — a
documented boundary, excluded from the crawl as before.

### A.3 The fa direction, tightened — and the real leaks

The fa crawl gained a **body-token rule**: any pure-alpha Latin
token ≥3 letters anywhere in visible text is a hit
(digit-bearing tokens are data; usernames count as user-chosen
identifiers). Census of the populated world, classified:

*Real leaks — FIXED:*
- `JournalEntry.source_type` had no `choices=`; templates
  rendered the 15 raw service codes (MANUAL, SALES_INVOICE,
  SALES_INVOICE_COGS, …) in both languages. Added
  `SOURCE_TYPE_LABELS` + `get_source_type_display()` (unknown
  codes fall back to the raw value), journal detail template
  uses it; all 15 labels translated in en.po.
- `StockDocument.__str__` interpolated raw doc_type/status
  codes — now the fields' translated display labels.
- Cheque detail rendered raw direction (RECEIVED) — now
  `get_direction_display`.
- Party detail's `{% blocktrans %}active={{ party.is_active }}`
  rendered literal `True`/`False` — restructured to بله/خیر.

*Defended allowlist additions* (each justified inline in the
test): `QFX` (file-format name), `Excel` (product name), `IRR`
(ISO 4217 code), the statement-import CSV header names
`date/description/reference/amount/debit/credit` (the import
contract literally requires these strings in the uploaded
file — translating the instruction would break it), and
`Enter` (the physical key's own label; ADR-060 instructions).
One rule refinement, found by a full-suite run: the stock
movements page renders `document_id|truncatechars:8`, so a
UUID appears as a fragment like `bddca-…`; an all-letter first
segment tripped the token rule nondeterministically.
Hyphen/ellipsis-bearing words whose alphanumeric chars are
all hex are now exempt as identifier fragments (data, not
language) — real words still fail, verified directly.

### A.4 Killing the clone footgun

Reproduction first: a scratch copy of the tree with `.mo`
deleted — `manage.py check` fired the new warning twice;
runserver rendered the en login as «ورود | اکانتیکس» with
Persian labels, and the fa account form offered
Asset/Liability/Debit/Credit in English. **Both directions
broken from one cause.** After `scripts/dev_run.sh`: en login
"Sign in | Accountix", fa account form with zero English
options. Both directions fixed by the documented path.

- `scripts/dev_run.sh` — THE one-command clone startup: fails
  with a bilingual message + install hint if msgfmt is missing,
  then compilemessages → migrate → `exec runserver "$@"`.
- System check **`accountix.W001`** (Warning, core app): fires
  when any `locale/*/LC_MESSAGES/django.mo` is missing or older
  than its `.po`; silent when fresh — proven by 5 tests over
  temp LOCALE_PATHS copies (missing fires, stale fires, fresh
  silent, the real tree silent, a complete copy silent). It
  stays silent in the test suite (conftest compiles catalogs)
  and in the frozen bundle (ships `.mo`).
- `DEVELOPMENT.md` now documents dev_run.sh as the way to run
  a clone, with the manual commands kept as its explanation.

### A.5 Catalog end state

After all sprint strings (tour fixes none; scan workstream
+37): **1,249 entries per catalog**, en **0 empty**, fa **0
real gaps**, **0 fuzzy**, placeholder multisets mechanically
verified byte-exact in both directions, `msgfmt --check`
clean on both.

**Status: Implemented + Tested.**

---

## Workstream B — Tour activation root cause (ADR-059)

### B.1 Run-mode reproduction

| Mode | tour.js | app.css | Payload + hidden button |
|---|---|---|---|
| Standalone bundle (temp data dir) | 200 | 200 | present |
| Source runserver (local settings) | 200 | 200 | present |
| Django test client | — | — | present (Sprint 30 tests) |

Static serving and payload emission were never the problem in
any supported mode.

### B.2 The DOM harness (new, permanent)

`scripts/tour_dom_check/`: `dump_pages.py` renders real pages
via the test client (dashboard, sales list, sales create;
fa + en); `harness.mjs` loads the real `tour.js` + the page's
real payload in jsdom and checks: button computed-hidden BEFORE
JS on every page; revealed only where a tour exists; click →
walk every step asserting the real catalog titles; prev; Esc;
NO-tour pages keep the button hidden; zero JS errors. First
run reproduced a click that "did nothing": jsdom has no
`window.matchMedia` (the engine's reduced-motion probe threw)
— a jsdom gap, stubbed in the harness as scaffolding, exactly
like `scrollIntoView`. With the stub, the engine passed every
step check — **tour.js itself is sound**.

### B.3 Root cause

app.css carries the global rule
`button, .btn { display: inline-block }`. Author-origin display
declarations beat the UA stylesheet's
`[hidden] { display: none }` regardless of specificity — so
the tour button, rendered with the `hidden` attribute, was
**visible on every page**, including all pages with no tour,
where clicking it does nothing. A visible dead control is
exactly "I cannot activate the tour."

Fix (one rule, near the top of app.css, commented):
`[hidden] { display: none !important }` — the standard
contract, which also protects every other `hidden` control
(the scan modal/panels rely on it too). A suite test pins the
rule's presence. The reveal-in-JS design stays (ADR-059 gives
the reasoning: server-visible would recreate the dead control
for no-JS/no-tour pages).

Harness verdict after the fix: **30 checks, ALL DOM CHECKS
PASSED** (6 pages). Negative control: removing the rule in a
scratch copy reproduces exactly 6 failures — the guard can
fail. (jsdom's getComputedStyle ignores `!important` across
rules — a known jsdom gap — so the harness computes the
cascade verdict from the parsed stylesheet with spec
origin/importance precedence; documented in the harness.)

**Status: Implemented + Tested** (root cause proven, fixed,
and permanently guarded).

---

## Workstream C — Barcode/QR scanning in invoicing (ADR-060)

### C.1 Lookup endpoint

`GET /scan/lookup/?code=&company=` (core app, login + OPERATE):
exact `barcode` match first, then exact `sku`, company-scoped
via the standard company resolution, active products only.
200 → `{id, name, sku, barcode, unit_id, unit_label,
sale_price, purchase_price}`; 404 → translated
«کالایی با این کد یافت نشد.». No migration: Product already
has `barcode` + `sku`, and the product form already exposes
barcode with its label (verified — nothing to add).

### C.2 Scan widget (sales + purchase invoice create)

Shared `_scan_widget.html` + one module `static/js/scan.js`:
code input + add button (Enter works — precisely what USB HID
scanner guns send; the input has **no `name`**, so a gun's
Enter can never submit the invoice form); POS add semantics —
existing line → quantity +1 (decimal-safe), else first empty
line, else the formset's own add-row button; unit + reference
price filled per form mode; input cleared and refocused after
every add; transient aria-live flash (product name on success,
translated error on 404). All strings reach JS via
server-rendered `data-msg-*` attributes. No-JS: widget inert,
normal entry untouched (existing form tests green).

### C.3 Camera

Modal with live preview; decode order: native
`BarcodeDetector` (qr_code, ean_13, ean_8, upc_a, upc_e,
code_128, code_39) → vendored **jsQR 1.4.0** (Apache-2.0,
256,885 B, sha256 `bc40c8a1…f5fee0859`) for QR only.
Continuous scanning, 2.5 s per-code cooldown (a different
code adds immediately). Failure messages are specific and
bilingual: permission denied / no camera / insecure context
(explains localhost-or-HTTPS in plain words) / QR-only notice
when 1D decoding is unavailable — each names the manual
fallback. **Honest limit:** `getUserMedia` requires a secure
context — localhost and HTTPS work; a plain-HTTP LAN address
blocks cameras on phone AND desktop. Scanner guns and typing
are unaffected.

### C.4 Phone pairing

Desktop (OPERATE) clicks «اتصال گوشی» → `POST /scan/sessions/`
creates a `ScanSession` (core migration `0001_initial`):
only the token's SHA-256 is stored; company + creator bound;
10-minute expiry; caps of 3 live sessions/user and 120
submissions/session; the raw token appears once, as a link +
a QR rendered client-side by vendored **qrcode-generator
1.4.4** (MIT, 56,694 B, sha256 `18ae399f…f1bf1780`) — no
Python QR dependency. Phone: `GET /scan/<token>/` (no login;
the token is the credential) shows only company + creator,
with the same camera/manual scanner; each code is resolved
**on the phone side** inside the bound company — unknown
codes get an immediate «یافت نشد» on the phone and are never
queued; known codes queue a `ScanSubmission`. Desktop polls
every 2 s; submissions return exactly once (marked consumed
in the same transaction) and feed the same add path.
«قطع اتصال» revokes instantly. The submission POST is
CSRF-exempt by design (phone holds no session cookie; token +
liveness + caps are the posture — ADR-060); everything else
keeps full CSRF/auth. Both vendored files carry license files
+ sha256 rows in `static/THIRD_PARTY_NOTICES.md`, and the
zero-external test now covers scan.js strictly and the vendor
files for fetch-capable patterns (their inert comment/namespace
URLs documented in the test).

### C.5 Tests

14 server tests: barcode/SKU lookup, barcode-beats-SKU,
cross-company invisibility (lookup AND phone submit),
VIEWER 403s, anonymous redirects, the full pairing flow
(create → phone 200 → submit → poll-once → poll-empty),
wrong/expired/revoked token 404s, both caps, creator-only
results, widget presence on both forms. jsdom
`scan_harness.mjs` drives the REAL scan.js on the REAL sales
create page (fetch/camera stubbed as scaffolding): gun entry
fills line 1 (product, qty 1, reference price), repeat scan
increments to 2, second product fills line 2, unknown code
errors and leaves the form untouched, camera decode of the
second product increments it, pairing renders the QR SVG and
a polled phone result increments line 1 — **20 checks, ALL
SCAN DOM CHECKS PASSED**.

**Status: Implemented + Tested.** Not covered (stated
plainly): real camera hardware and real phone browsers (no
devices in this environment); the jsQR frame loop against a
live video feed (the BarcodeDetector path is the one
exercised end-to-end in jsdom; jsQR is upstream's verbatim
build, loaded and present, its decode loop smoke-checked only
for absence of errors when no frames are readable).

---

## Workstream D — UI/UX pass, bundle, docs

### D.1 UI/UX review (Nielsen heuristics + form-design path discipline)

Three surfaces, walked end-to-end the way form-design
prescribes (the respondent's path, not the designer's):

1. **Language switcher.** The switcher names each language in
   its own script («فارسی» / English) — the endonym convention
   is the right pattern (a user lost in the wrong language can
   still recognize their own), so no change; the en crawl's
   single defended Arabic token pins it. Finding recorded:
   correctness of the switcher was never the problem — the
   uncompiled-catalog fallback was, and §A.4's W001 warning
   now names the cure at the moment it happens (visibility of
   system status).
2. **Tour entry point.** Heuristic failure found and fixed:
   a visible control that does nothing is worse than no
   control (error prevention + honesty of affordances). With
   the `[hidden]` contract restored, the button exists exactly
   where a tour will actually run; no-JS users never see it.
   No further change — inventing a second entry point would
   add clutter, not clarity.
3. **Scan/pairing flow.** Applied during the build, verified
   by the jsdom path-walk: one field, one job (the code input
   cannot submit the form — error prevention); focus returns
   to the input after every add so scanning is a single
   repeated gesture (minimal memory load); every outcome is
   announced in an aria-live flash naming the product
   (visibility of system status); the pairing panel states
   the 10-minute expiry BEFORE the user connects (informed
   expectations); every camera failure message names its own
   recovery (type the code / use a gun); the phone page shows
   company + creator so the phone user can verify they are
   feeding the right invoice before scanning (recognition +
   trust). Label check: the input is labeled
   «بارکد یا کد کالا (SKU)» with a placeholder that teaches
   the gesture («اسکن کنید یا کد کالا را بنویسید و Enter
   بزنید»).

### D.2 Bundle + frozen smoke

`scripts/build_linux.sh` rebuilt `dist/` (plain rebuild;
`package_release.sh` NOT run; the 1.1.0 artifact untouched).
Frozen smoke against a fresh data dir: statics 200
(tour.js, scan.js, app.css, both vendor files); login → setup
302; setup creates admin + company; dashboard 200 showing
**1.1.0** with the tour payload; sales create 200 with the
scan widget; pairing session created from the bundle (200
JSON with phone/results/revoke URLs); the phone URL serves
200 without login and names the company. No W001 in the
bundle (it ships compiled `.mo`).

### D.3 Gates

- pytest: **500 passed + 3 skipped** (+24 vs baseline:
  14 scan server + 5 catalog check + 4 en crawl + 1 CSS pin;
  the fa crawl's 2 tests now enforce the tightened rule).
- `manage.py check`: clean under local, standalone, and test
  settings. `makemigrations --check`: no changes (the one new
  core migration `0001_initial` is committed).
- mypy: clean (197 files). ruff: clean.
- msgfmt --check: both catalogs clean; 0 fuzzy; placeholder
  multisets verified mechanically.
- Both crawl tests green; zero-external scan green;
  `scripts/tour_dom_check/run.sh` green end-to-end from a
  cold scratch dir (tour 30 checks + scan 20 checks).
- Docs: ADR-058/059/060 appended; CURRENT_STATE.md and
  DEVELOPMENT.md updated.

### Remaining limitations (unchanged or stated)

- Windows bundle: still the only NOT VERIFIED release gate.
- Real-camera/real-phone verification needs hardware; the
  secure-context constraint (localhost/HTTPS) is a browser
  platform rule, surfaced in-product.
- Stored history keeps its creation language (Sprint 30
  decision); the new source-type labels render bilingually
  because they are labels, not stored text.
