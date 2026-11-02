# Inventory Rules

**Status: entirely Planned.** No inventory code exists in Sprint 01.
These are the binding requirements for Phase 3.

1. Ledger-based: `StockMovement` is the authoritative record; a product
   quantity field alone is never the source of truth. `StockBalance` is a
   derived/reconcilable projection of movements.
2. Every movement records company, warehouse, product, quantity change,
   value change, date, source document, responsible user, timestamp.
3. Valuation: Moving Weighted Average Cost in v1; the design must allow
   FIFO later. Receipts update average cost; issues consume at current
   average; COGS comes from that valuation.
4. Negative available stock is prevented by default; any override must be
   an explicit, audited company setting.
5. Transfers move quantity between warehouses with paired movements and
   no valuation change in total.
6. Returns and adjustments are movements with their own document types —
   never edits to historical movements.
7. Backdated movements require revaluation rules to be defined and tested
   before the feature ships; until then backdating is restricted.
8. Inventory valuation must reconcile with the inventory accounting
   account in the general ledger; reconciliation reports are derived
   from movements + journal lines.
