# Sprint 05 Report — Sales (Phase 5) — INTERNAL MVP MILESTONE

Date: 2026-11-02. Base: Sprint 04 local commit `472f9ec`.
Environment: Python 3.12.3, Django 5.2.18, SQLite (local/test).
PostgreSQL was **not** available on this machine — the suite was not run
against it; this remains a stated limitation, not a silent skip.

## Internal MVP status

**The internal MVP, as defined in the PRD (§10) and master prompt §20.4,
is reached.** The dedicated end-to-end test
(`apps/sales/tests/test_mvp_e2e.py`) runs one continuous workflow with
numeric assertions at every stage:

1. Company + fiscal year/period + chart of accounts (cash, receivables,
   inventory, input VAT, payables, output VAT, revenue, COGS, expense).
2. Supplier, customer, product, warehouse created.
3. Purchase posted: 10 @ 100 + 10% tax → grand 1100; stock 10 / value
   1000 / MWAC 100; supplier subledger 1100.
4. Sale posted: 4 @ 250 + 10% tax → grand 1100; COGS exactly 400 (issue
   value at MWAC); stock 6 / value 600; AR subledger 1100.
5. Reconciliations: trial balance balances (Dr = Cr = 2600 at that
   stage); inventory valuation (600) == GL inventory account balance;
   AP subledger total (1100) == AP account; AR subledger total (1100)
   == AR account; revenue −1000, output VAT −100, COGS 400.
6. A customer payment is recorded **as a plain manual journal** through
   the accounting service (Dr cash / Cr receivables, party-tagged) —
   AR subledger drops to 0, trial balance still balances.

What this does **not** mean: the product is not commercially ready
(v1.0). There is no treasury (the payment above is a test-only journal;
`payment_status` deliberately stays UNPAID and is asserted to stay
UNPAID), no payment allocation, no balance sheet / income statement, no
printing/PDF, no launcher, no PostgreSQL concurrency evidence, no
posting forms in the UI, and the GitHub copy is still not a runnable
clone (Sprint 01 leftovers, separately tracked). Per the master prompt,
the MVP working is explicitly *not* a release criterion.

## Implemented (verified by tests)

- **Parties**: `parties.services.require_customer` added (mirror of
  `require_supplier`); a supplier-only party is rejected by sales flows.
- **Sales app** (installed, migration `sales/0001`): `SalesQuotation` +
  lines (DRAFT/SENT/CONVERTED/CANCELLED), `SalesInvoice` + lines,
  `SalesReturn` + lines — all mirroring the ADR-016 purchasing
  conventions: warehouse per invoice, numbers unique per company,
  line-level absolute discount only, per-line tax rate snapshot + tax
  amount snapshot at posting, totals snapshot == sum of lines, and
  `payment_status` as a dimension separate from posting `status`
  (starts UNPAID; nothing in this sprint moves it). Posted documents
  and lines are immutable (model guards; only POSTED → REVERSED flip).
- **Posting service** (`sales/services.py`, atomic, validate-before-write):
  - Totals with `Decimal`, identical math to purchasing.
  - Stockable lines are issued through the inventory services at the
    current MWAC; insufficient stock rejects the **whole** posting —
    invoice stays DRAFT, no movements, no journals (tested).
  - GL is opt-in (ADR-013): caller supplies `gl_accounts={receivables,
    revenue, tax_payable, cogs, inventory}` and **two** entries post
    (ADR-020): revenue entry Dr receivables (grand, party-tagged) /
    Cr revenue (net) / Cr tax payable (tax), key `sales-invoice:<id>`;
    COGS entry Dr COGS / Cr inventory at the issue value, key
    `sales-invoice-cogs:<id>`. Without accounts: stock issues, both
    journal fields NULL (tested). Service lines: revenue only, no stock
    document, no COGS entry. Re-posting is idempotent.
  - **Reversal** reverses both journals and the stock issue in one
    transaction (stock returns to the warehouse; subledger nets to
    zero via the kept party tag); double reversal rejected.
  - **Returns** (`post_sales_return`): cumulative quantity validation
    per invoice line; stock received back at the **original sale's COGS
    unit cost** (ADR-021) read from the original issue movements;
    revenue/tax reversed proportionally (Dr revenue + Dr tax payable /
    Cr receivables, party-tagged; Dr inventory / Cr COGS at the restored
    value), keys `sales-return:<id>` / `sales-return-cogs:<id>`.
  - **Quotation conversion** (`convert_quotation_to_invoice`): copies
    lines into a DRAFT invoice, links it, flips the quotation to
    CONVERTED; reconversion rejected.
- **Customer subledger**: `sales/reporting.py` derives `customer_balance`,
  `accounts_receivable`, `ar_total` from party-tagged journal lines on
  the receivables account only (ADR-015), plus `customer_statement`
  (balance + invoices + returns), sales histories per customer/product.
  Reconciliation (Σ customer balances == trial-balance receivables) is
  asserted in the E2E test and the posting test.
- **Minimal UI** (read-only, Persian RTL, membership-filtered): sales
  invoice list + detail (`/sales/invoices/...`), AR summary
  (`/sales/receivables/`), customer statement (`/sales/statement/`).
  Nav links added. No posting forms.

## Tested — exact evidence (2026-11-02, this machine)

| Command | Result |
|---|---|
| `manage.py makemigrations sales` | Created `sales/0001_initial` |
| `manage.py check --settings=config.settings.test` | "System check identified no issues (0 silenced)" |
| `manage.py makemigrations --check --dry-run` | "No changes detected" |
| `manage.py migrate` (local settings, SQLite) | `sales.0001` applied OK |
| `.venv/bin/python -m pytest` (repo root) | **115 passed, 0 failed** (99 prior + 16 new: sales 15 + MVP E2E 1) |
| `ruff check backend tests` | "All checks passed!" |
| `ruff format --check backend tests` | "109 files already formatted" |

New tests cover: the E2E posting (totals, tax snapshot, COGS 400, stock
6/600, AR subledger == GL), exact discount+tax math on a non-even case
(3 @ 33.33 − 1.00 → net 98.99, tax 9.90, grand 108.89), service-line
sale (revenue, no stock/COGS), the no-GL path, idempotent re-post,
insufficient-stock atomic rejection, cross-company customer/product/
warehouse rejection, supplier-is-not-a-customer rejection, closed-period
rejection, full reversal restoring stock and zeroing AR/revenue/COGS,
partial return (stock and AR exact), over-return rejection, the
ADR-021 proof (return restores at original COGS 100 after MWAC moved to
225; restored value 200, not 450), quotation conversion + reconversion
rejection, reporting histories/statement, invoice view isolation, and
the §20.4 MVP end-to-end workflow.

## Partially implemented

- UI is read-only; no quotation/invoice/return forms yet.
- Quotations are master data + conversion only: no quotation totals
  snapshot, no expiry enforcement (`valid_until` is informational).
- Sales returns cannot themselves be reversed (status REVERSED reserved
  on the model; no service — same stance as purchase returns).
- Subledger caveat (ADR-015) applies symmetrically: manual journal
  lines on the receivables account without a party tag are invisible to
  the AR subledger (the MVP payment is therefore tagged deliberately).

## Planned / not started

- Treasury (Sprint 06): cash/bank accounts, receipts/payments, payment
  allocation — the only writer allowed to move `payment_status` —
  and Iranian cheque workflows.
- Financial statements (balance sheet, income statement), period closing,
  opening balances.
- Invoice printing/PDF, document numbering service.
- `AccountingMapping` remains deferred (ADR-011).

## Blocked / limitations

- PostgreSQL not run — no server/binaries on this machine; concurrency
  invariants remain proven on SQLite only.
- Type checking (pyright/mypy) still not configured/run.
- Python 3.12.3 on this machine (prompt targets 3.13).
- GitHub push: Sprint 05 core files are pushed file-by-file via the
  connector in one end-of-sprint sync and verified by read-back in the
  coordinator's delivery report; this file does not claim a push
  outcome sight-unseen. The separately tracked Sprint 01 leftover files
  were not touched, so a fresh GitHub clone is still not runnable
  end-to-end; the local tree remains the source of truth.

## Recommended next phase — Sprint 06 (Treasury, Phase 6)

Cash/bank accounts, receipts and payments with allocation to invoices,
moving `payment_status` from real allocations, cheque register with
Iranian workflows (due dates, status tracking), treasury reports — and
replacing the MVP test's manual-journal payment with a real allocated
receipt in a treasury end-to-end test.
