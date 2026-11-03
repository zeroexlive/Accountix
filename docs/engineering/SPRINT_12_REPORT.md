# Sprint 12 Report — Data-Entry UI

Sprint goal: close the headline v1.0 limitation from Sprint 10's
release gate — the web UI was read-only for business documents.
Outcome: **the UI is now fully writable for business documents**,
exclusively through the existing service layer (ADR-039). No model
changes; `makemigrations --check` reports "No changes detected".

## Implemented (per scope letter)

- **A. Parties** — create + edit forms (`PartyForm`) with contact and
  address inline formsets (both optional), a party detail page, a
  "طرف‌حساب جدید" button on the list and ویرایش on the detail. The
  company is fixed on edit (a party must not hop companies and orphan
  its subledger history).
- **B. Catalog** — product create/edit with company-scoped unit and
  category pickers; single create forms for Unit, ProductCategory
  and Warehouse, all reachable from the inventory product list. The
  models' `clean()` (the catalog services' validation, ADR-002)
  remains the final cross-company guard.
- **C. Purchases** — invoice create form (supplier, warehouse, date,
  number, line formset: product/unit/quantity/unit cost/discount/tax)
  → DRAFT via `create_purchase_invoice`; detail-page post action with
  per-document GL pickers (payables always; inventory/expense/tax
  only when the document actually needs them, computed from
  `compute_invoice_totals`) → the atomic stock + AP service; reverse
  action with optional reason; purchase return create (per-line
  purchased/returned/remaining shown) + detail + post + reverse.
- **D. Sales** — mirror of C (customer, lines with price/discount/
  tax; post pickers receivables/revenue/tax payable/COGS/inventory;
  returns restore at original COGS, ADR-021), plus reverse.
- **E. Treasury** — treasury account create (CASH/BANK + linked GL,
  ADR-022); payment create (direction, party scoped by direction,
  treasury account, method, cheque detail fields required when
  method=CHEQUE) → DRAFT; post action with counterparty (+ cheque
  holding) pickers; allocation UI on the payment detail — one amount
  input per open invoice of the party, each row allocated by
  `allocate_payment` on its own, service errors surfaced per invoice;
  void-allocation action (void, never delete, ADR-025); payment
  reverse; cheque detail with exactly the transitions the services
  expose — deposit, clear (with destination bank picker), bounce,
  return for received cheques; clear/bounce for issued ones.
  `payment_status` moves only via the treasury recompute (ADR-024):
  the UI never writes it.
- **F. Manual journal entries** — create form (date, description,
  optional idempotency key — the view generates `manual:<uuid4>` when
  blank; line formset: account, debit, credit, description, optional
  party tag) → DRAFT; detail page with lines/totals, post and reverse
  actions.
- **G. Navigation** — create buttons on every list page (parties,
  products, purchase/sales invoices, treasury accounts, payments,
  journal); sidebar active-state conditions extended so create,
  detail and action pages highlight their section. The Sprint 11
  sidebar test (22 URL names resolve + render) passes unchanged.

## Service functions added (and why)

Accounting was the one app whose contract did not fit the UI's
draft→post flow: it exposed only the atomic `post_journal_entry`.
Two thin functions were added to `apps/accounting/services.py`,
following the module's own patterns:

- `create_journal_draft(*, company, entry_date, lines, description="",
  user=None, idempotency_key=None)` — validates the lines with the
  same §6.3 `_validate_lines` used at posting, resolves the fiscal
  period (which must exist but need not be OPEN), rejects a duplicate
  idempotency key (unlike `post_journal_entry`, which returns the
  existing entry — a form user must be told their key collides),
  saves a DRAFT with `source_type="MANUAL"` and records a
  `journal.draft_created` audit event.
- `post_journal_draft(entry, *, user=None)` — re-resolves the period
  and requires it OPEN, re-validates the stored lines end to end
  (accounts may have been deactivated since the draft), posts, and
  records `journal.posted`. Re-posting a POSTED entry returns it
  unchanged (the `post_*` convention of the other apps); a REVERSED
  entry raises.

No other service was added: purchases, sales and treasury already had
create/post/reverse service pairs, and master data uses the Sprint 01
ModelForm pattern (model `clean()` runs the services' validation).
Shared plumbing added: `apps/core/access.py::resolve_scoped_company`
(+ `require_posted_company_member` for the ModelForm create views),
`apps/core/forms.py::add_service_errors` / `date_widget`, and
`apps/accounting/forms.py::eligible_accounts` / `account_field` —
the single place that defines GL-picker eligibility (active +
postable, optional type filter, same company).

## Tested

Suite: **258 passed, 3 skipped** on SQLite (baseline 214 + 3; 44 new
tests, 0 regressions). Gates: `manage.py check` clean, mypy clean
(155 files), `ruff check` clean, `ruff format --check` clean,
`makemigrations --check --dry-run` → "No changes detected".

Commands (repo root): `.venv/bin/python -m pytest`,
`.venv/bin/python backend/manage.py check --settings=config.settings.test`,
`cd backend && ../.venv/bin/mypy --config-file ../pyproject.toml .`,
`.venv/bin/python -m ruff check backend`,
`.venv/bin/python backend/manage.py makemigrations --check --dry-run --settings=config.settings.test`.

### Golden-path E2E (`apps/treasury/tests/test_ui_e2e.py`)

Stage fixtures are only the company, fiscal period and chart of
accounts; every business object is created/posted through UI forms:

1. Supplier, unit, warehouse, product via the UI forms.
2. Purchase invoice via form, 10 @ 100, tax 0.1 → post via UI →
   stock **10 / value 1000**, AP subledger **1100**.
3. Customer via form; sales invoice via form, 4 @ 250, tax 0.1 →
   post via UI → stock **6 / value 600**, AR subledger **1100**,
   COGS account balance **400** (4 @ MWAC 100), revenue **−1000**.
4. Treasury account via form; cash receipt 1100 via form → post via
   UI → cash GL **1100**; allocate 1100 via the allocation UI →
   sales invoice `payment_status == "PAID"`; trial balance balanced.

### Per-area UI tests (all through the test client)

- Journal service (9) + UI (5): draft doesn't move the trial
  balance; post moves it (cash +500 / revenue −500); reverse returns
  both balances to zero.
- Parties (5): create with contact + address inlines; create with
  empty inlines; edit keeps the company; detail/edit of another
  company's party → 404.
- Catalog (4): unit/category/warehouse/product create, product edit,
  cross-company unit pick rejected with nothing saved.
- Purchases (6): create+post numeric assertions; return of 3 → stock
  7/700, AP 1100 → 800 (returns reverse AP at goods value, the
  Sprint 04 service semantics); invoice reverse restores stock/AP
  to zero.
- Sales (5): create+post (stock 6, AR 1100); return of 1 restores
  stock at the original COGS 100 (stock 7/700, AR 825); reverse.
- Treasury (9): account create; receipt → allocate → PAID; void →
  UNPAID; payment reverse voids allocations and zeroes the cash GL;
  cheque receipt sits in-hand (bank 0, cheques-in-hand 1100) →
  allocate → PAID → clear into the bank account (bank 1100,
  in-hand 0); bounce reopens the invoice (UNPAID, in-hand 0);
  supplier payment allocates to a purchase invoice → PAID.

### Negative / permission tests

- Non-member POST create → 404, nothing created (journal, party,
  product master data, purchase, sales, payment).
- Detail/action endpoints of another company's objects → 404
  (journal detail + post, party detail/edit, payment detail).
- Cross-company GL account id in a post form → form error, invoice
  stays DRAFT, stock unchanged (purchases post; journal line account
  from another company likewise rejected at create).
- Oversell: sales invoice for 5 with stock 2 → post renders the
  service error, invoice stays DRAFT, stock stays 2, AR stays 0.
- Unbalanced journal via the form → non-field errors with the
  service's message, nothing persisted; two-sided lines and
  duplicate idempotency keys rejected at the service level.
- Over-allocation (1200 against an 1100 invoice) → service error
  surfaced, no allocation row, invoice stays UNPAID.
- Over-return: a purchase return of 11 against 10 purchased may be
  drafted but its post is rejected by the service; stock/AP
  unchanged, error surfaced (the cap is a posting rule, Sprint 04).
- Closed period: a journal draft may be created for a date in a
  closed period but `post_journal_draft` rejects it; invoice
  posting into closed periods stays gated by the existing services.

## Partially implemented

- None of A–G is partial. Two deliberate narrowings, both inherited
  from the service contracts rather than the UI: purchase/sales
  return quantities are capped at **post** time (drafts may exceed —
  the Sprint 04/05 rule, asserted by test), and purchase returns
  reverse AP at goods value without a tax reversal, exactly as the
  Sprint 04 service posts them.

## Planned (not in this sprint)

- Data-entry polish: opening balances UI, stock count UI, fiscal
  closing UI (their services exist; the pages are still read-only).
- Bank reconciliation and cheque books (Sprint 06 limitations).
- Jalali date display (dates are still entered/shown Gregorian).

## Blocked

- Nothing in the sprint scope is blocked.

## Effect on RELEASE_READINESS wording

`docs/engineering/RELEASE_READINESS.md` is a Sprint 10 artifact and
was **not** rewritten — its verdict stands as the record of the
Sprint 10 gate. Its limitation #1 ("the web UI is read-only for
business documents") is **closed by this sprint** and should be read
as historical; `CURRENT_STATE.md` records the closure. The other
readiness items are unchanged: the PostgreSQL restore drill and the
Windows bundle remain NOT VERIFIED, and there is still no login rate
limiting (fine for loopback, blocking for internet-facing deploys).

## Known limitations of this sprint's UI

- Allocation is one payment → its party's open invoices; a single
  payment cannot be split across parties (the service model does not
  allow it either).
- With JavaScript disabled, the number of lines on a new invoice or
  journal is bounded by the rendered `extra` rows (3 for invoices, 4
  for journals) — there is no draft-edit page yet, so a longer
  document needs the (tiny, optional) JS add-row button. Return
  formsets are unaffected: their rows are the original invoice's
  lines by construction.
- Cheque "return to issuer" is wired for received cheques (the only
  direction the service exposes it for); issued cheques expose
  clear/bounce only, matching the service state machine.

## Recommended Sprint 13

**Data-entry completion: opening balances UI, stock count UI,
fiscal closing UI** — the three remaining service-backed workflows
that still have read-only pages — followed by Jalali display of
dates across the UI (entry stays Gregorian underneath). Bank
reconciliation remains the largest unbuilt treasury feature and is
the natural Sprint 14.
