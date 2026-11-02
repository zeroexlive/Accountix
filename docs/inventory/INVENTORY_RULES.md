# Inventory Rules

**Status: implemented in Sprint 03** (catalog + inventory apps, migrations
`catalog/0001`, `inventory/0001`). Rules below describe the behaviour as
implemented and tested; remaining gaps are called out explicitly.

1. Ledger-based: `StockMovement` is the authoritative record; a product
   quantity field alone is never the source of truth. There is **no**
   StockBalance table — balances are a derived projection of movements
   (`apps/inventory/reporting.py`, ADR-012), reconciled by tests that
   compare reported balances against raw movement sums.
2. Every movement records company, warehouse, product, quantity change
   (signed, in the product's base unit), unit cost (the moving average at
   that moment; for receipts the receipt cost per base unit), value change
   (signed), movement date, source document + line, responsible user and
   timestamp. Movements are append-only: model guards reject updates and
   deletes.
3. Valuation: Moving Weighted Average Cost per (company, warehouse,
   product). Receipts are valued at the line unit cost (priced per line
   unit, converted to base-unit cost); issues are valued at the current
   average. Issuing the entire remaining quantity takes the entire
   remaining value, so a zero-quantity balance is always zero-value.
   FIFO may be added later; nothing in the ledger shape prevents it.
4. Negative available stock is prevented: issues, transfers-out,
   negative adjustments and reversals that would drive a balance negative
   are rejected *before any movement is written*, and the whole document
   rolls back (no movements, and — via the wrappers' outer transaction —
   no orphan draft document either). There is no override setting yet;
   the prompt's "explicit audited override" remains planned.
5. Transfers move quantity between warehouses of the same company with
   paired movements at the source warehouse's current average: total
   quantity and total value across the company do not change.
6. Returns and adjustments are movements with their own documents —
   never edits to historical movements. Adjustment lines carry a signed
   quantity (the sign is the direction) and the reason is stored as the
   document description. A positive adjustment with no existing stock
   requires an explicit unit cost.
7. Backdating: movements are applied in **posting order**, valued at the
   average at posting time, regardless of document date. True backdated
   revaluation is not implemented and remains restricted until its rules
   are defined and tested.
8. Accounting integration: inventory valuation reconciles with the GL
   only for documents whose caller explicitly opted into GL posting
   (`gl_accounts=...`, ADR-013). The stock document stores the resulting
   journal entry; reversing such a document also reverses its journal in
   the same transaction. There are no hardcoded account codes.
9. Posting lifecycle mirrors the journal: DRAFT → POSTED → REVERSED.
   Posted documents and their lines are immutable (model guards); a
   reversal creates a new posted document with exactly negating
   movements plus a `StockDocumentReversal` record. Unit conversions are
   product-scoped (`1 from = factor × to`, reverse divides) and stock
   lines are converted to the product's base unit before any movement is
   planned.
10. Company isolation: warehouses, products, units, conversions and GL
    accounts of another company are rejected by the services; quantities
    and costs are `Decimal` end-to-end.

## Stock counting — implemented in Sprint 07 (ADR-027)
11. `create_inventory_count` snapshots each line's `system_qty` from the
    **derived** balance at creation; `counted_qty` is what was counted;
    `variance = counted − system`. One line per product per count.
12. Warehouse-freeze rule: `post_inventory_count` re-derives every
    counted product's balance and **rejects** the count if it no longer
    equals the snapshot — the warehouse must not move between counting
    and posting. A stale count is voided and recounted, never silently
    re-snapshotted.
13. Posting writes ONE `ADJUSTMENT` document (source `INVENTORY_COUNT`)
    with only the non-zero variance lines, valued at the current MWAC
    (rule 3). A positive variance with zero stock requires an explicit
    `unit_cost` on the line (rule 6). A fully zero-variance count posts
    with no document. GL opt-in (rule 8): caller supplies `inventory` +
    `variance` accounts; the **net** variance value posts once (gain:
    Dr inventory / Cr variance; loss mirrored), key `stock-count:<id>`.
14. `reverse_inventory_count` reverses the journal and the stock
    document and stores a POSTED reversal count with system/counted
    swapped and `reversal_of` set; the original flips to REVERSED.
    Posted counts and their lines are immutable; reversing a reversal
    is rejected.

## Opening stock — recipe, Sprint 07 (ADR-029)
15. There is deliberately **no** opening-stock model. Opening stock is
    an ordinary receipt: `receive_stock(..., source_type="opening_stock",
    source_id=<fiscal-year label>, unit_cost=<opening unit cost>)`, with
    the GL opt-in pair `(inventory_account, opening_equity_account)` to
    post Dr inventory / Cr opening equity in the same step. The receipt
    is a normal document afterwards (reversible, auditable). Covered by
    `test_opening_stock_via_receipt_with_gl`.
