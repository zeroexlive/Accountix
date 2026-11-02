# Entity Relationship Diagram

Legend: **[S01]/[S02]/[S03]/[S04]/[S05]/[S06]/[S07]** = implemented with migrations in that sprint.
**[planned]** = full target schema from the master prompt §13.2; no model
exists yet. JournalEntry/JournalLine/JournalReversal moved to [S02] —
implemented 2026-11-02; their relations above lost the "[planned]" prefix
accordingly in the diagram relations for FiscalPeriod/Account (textual
markers in relation labels were simplified — the entity blocks are the
source of truth for status). All planned entities will carry `id (UUID PK)`, `created_at`,
`updated_at`, and a `company` FK unless noted. Monetary fields are Decimal.

```mermaid
erDiagram
    User ||--o{ CompanyMembership : "belongs via"
    Company ||--o{ CompanyMembership : has
    Company ||--o{ Branch : has
    Company ||--o{ FiscalYear : has
    FiscalYear ||--o{ FiscalPeriod : contains
    Company ||--o{ FiscalPeriod : has
    Company ||--o{ Account : owns
    Account ||--o{ Account : "parent of"
    Company ||--o{ AuditEvent : "scoped to"
    User ||--o{ AuditEvent : "acts in"

    Company ||--o{ Party : owns
    Party ||--o{ PartyContact : has
    Party ||--o{ PartyAddress : has
    Party ||--o{ JournalLine : "tagged on (subledger, ADR-015)"
    Company ||--o{ ProductCategory : owns
    ProductCategory ||--o{ Product : contains
    Unit ||--o{ ProductUnitConversion : converts
    Product ||--o{ ProductUnitConversion : has
    Product ||--o{ ProductPrice : "[planned]"
    Company ||--o{ Warehouse : owns
    Warehouse ||--o{ StockMovement : holds
    Product ||--o{ StockMovement : moves
    StockDocument ||--o{ StockDocumentLine : has
    StockDocument ||--o{ StockMovement : generates
    InventoryCount ||--o{ InventoryCountLine : "[S07] has"
    FiscalPeriod ||--o{ JournalEntry : "[planned] period of"
    JournalEntry ||--o{ JournalLine : "[planned]"
    Account ||--o{ JournalLine : "[planned] posted to"
    JournalEntry ||--|| JournalReversal : "[planned] reversed by"
    Party ||--o{ SalesInvoice : "[S05] customer"
    TreasuryAccount ||--o{ Payment : "[S06] settles through"
    Party ||--o{ Payment : "[S06] counterparty"
    Payment ||--o{ PaymentAllocation : "[S06] allocates"
    PaymentAllocation }o--|| SalesInvoice : "[S06] settles"
    PaymentAllocation }o--|| PurchaseInvoice : "[S06] settles"
    Payment ||--o{ Cheque : "[S06] paid by"
    SalesInvoice ||--o{ SalesInvoiceLine : "[S05] has"
    Product ||--o{ SalesInvoiceLine : "[S05]"
    SalesQuotation ||--o{ SalesInvoice : "[S05] converts to"
    Party ||--o{ PurchaseInvoice : supplier
    PurchaseInvoice ||--o{ PurchaseInvoiceLine : has
    PurchaseOrder ||--o{ PurchaseInvoice : fulfilled by
    PurchaseInvoice ||--o{ PurchaseReturn : "returned via"
    PurchaseReturn ||--o{ PurchaseReturnLine : has
    Company ||--o{ Payment : "[planned]"
    Payment ||--o{ PaymentAllocation : "[planned]"
    SalesInvoice ||--o{ PaymentAllocation : "[planned] settled by"
    PurchaseInvoice ||--o{ PaymentAllocation : "[planned] settled by"
    CashAccount ||--o{ Payment : "[planned]"
    BankAccount ||--o{ Payment : "[planned]"
    BankAccount ||--o{ Cheque : "[planned]"

    User { uuid id PK; string username UK; string password_hash; bool is_active }
    Company { uuid id PK; string name; string default_currency "IRR"; bool is_active }
    Branch { uuid id PK; uuid company FK; string code "UK per company" }
    CompanyMembership { uuid id PK; uuid company FK; uuid user FK; string role; "UK(company,user)" x }
    FiscalYear { uuid id PK; uuid company FK; date start_date; date end_date; string status; "no overlap per company (service)" x }
    FiscalPeriod { uuid id PK; uuid company FK; uuid fiscal_year FK; date start_date; date end_date; string status }
    Account { uuid id PK; uuid company FK; uuid parent FK "nullable"; string code "UK per company"; string account_type; string normal_balance; bool is_postable; bool is_active }
    AuditEvent { uuid id PK; uuid company FK "nullable"; uuid user FK "nullable"; string action; string entity_type; string entity_id; json metadata }
    JournalEntry { uuid id PK "[S02]"; uuid company FK; uuid fiscal_period FK; date entry_date; string status "DRAFT/VALIDATED/POSTED/REVERSED"; string idempotency_key "UK per company, partial"; uuid reversal_of FK "nullable" }
    JournalLine { uuid id PK "[S02]"; uuid entry FK; uuid account FK; uuid party FK "nullable, subledger tag [S04]"; decimal debit; decimal credit; "checks: >=0, one side only, non-zero" x }
    Party { uuid id PK "[S04]"; uuid company FK; string kind "SUPPLIER/CUSTOMER/BOTH"; string code "UK per company"; string name; string tax_id; bool is_active }
    PartyContact { uuid id PK "[S04]"; uuid party FK; string full_name; string phone; string email; bool is_primary }
    PartyAddress { uuid id PK "[S04]"; uuid party FK; string label; string city; string postal_code }
    PurchaseOrder { uuid id PK "[S04]"; uuid company FK; uuid supplier FK; string order_number "UK per company"; string status "DRAFT/APPROVED/CLOSED/CANCELLED" }
    PurchaseInvoice { uuid id PK "[S04]"; uuid company FK; uuid supplier FK; uuid warehouse FK; string invoice_number "UK per company"; string status "DRAFT/POSTED/REVERSED"; string payment_status "separate dimension"; decimal grand_total "snapshot = sum of lines"; uuid stock_document FK "nullable"; uuid journal_entry FK "nullable, GL opt-in" }
    PurchaseInvoiceLine { uuid id PK "[S04]"; uuid invoice FK; uuid product FK; decimal quantity; decimal unit_cost; decimal discount_amount; decimal tax_rate "snapshot"; decimal tax_amount "snapshot" }
    PurchaseReturn { uuid id PK "[S04]"; uuid company FK; uuid original_invoice FK; string return_number "UK per company"; string status; decimal total_amount "MWAC value relieved" }
    PurchaseReturnLine { uuid id PK "[S04]"; uuid purchase_return FK; uuid invoice_line FK; uuid product FK; decimal quantity }
    JournalReversal { uuid id PK "[S02]"; uuid original_entry FK "OneToOne"; uuid reversal_entry FK "OneToOne"; uuid reversed_by FK "nullable"; string reason }
    Product { uuid id PK "[S03]"; uuid company FK; string sku "UK per company"; string barcode; bool is_stockable; bool is_active; decimal min_stock_level; uuid base_unit FK; uuid category FK "nullable" }
    Unit { uuid id PK "[S03]"; uuid company FK; string code "UK per company"; string name }
    ProductCategory { uuid id PK "[S03]"; uuid company FK; uuid parent FK "nullable"; string code "UK per company" }
    ProductUnitConversion { uuid id PK "[S03]"; uuid product FK; uuid from_unit FK; uuid to_unit FK; decimal factor "check > 0" }
    Warehouse { uuid id PK "[S03]"; uuid company FK; string code "UK per company"; bool is_active }
    StockDocument { uuid id PK "[S03]"; uuid company FK; uuid warehouse FK; uuid destination_warehouse FK "nullable, transfers"; string doc_type "RECEIPT/ISSUE/TRANSFER/ADJUSTMENT"; string status "DRAFT/POSTED/REVERSED"; uuid reversal_of FK "nullable"; uuid journal_entry FK "nullable, GL opt-in" }
    StockDocumentLine { uuid id PK "[S03]"; uuid document FK; uuid product FK; uuid unit FK; decimal quantity "signed only for ADJUSTMENT"; decimal unit_cost "nullable" }
    StockMovement { uuid id PK "[S03]"; uuid company FK; uuid warehouse FK; uuid product FK; decimal quantity_delta "signed, base unit"; decimal unit_cost "MWAC at movement"; decimal value_delta "signed"; uuid document FK; "append-only (model guards)" x }
    StockDocumentReversal { uuid id PK "[S03]"; uuid original_document FK "OneToOne"; uuid reversal_document FK "OneToOne" }
    StockBalance { string note "NOT A TABLE - derived from StockMovement in inventory.reporting (ADR-012)" }
    InventoryCount { uuid id PK "[S07]"; uuid company FK; uuid warehouse FK; date count_date; string status "DRAFT/POSTED/REVERSED"; uuid stock_document FK "nullable"; uuid journal_entry FK "nullable, GL opt-in"; uuid reversal_of FK "nullable" }
    InventoryCountLine { uuid id PK "[S07]"; uuid count FK; uuid product FK; decimal system_qty "snapshot at creation"; decimal counted_qty; decimal unit_cost "nullable, required for +variance with zero stock"; "UK (count, product)" x }
    SalesInvoice { uuid id PK "[S05]"; uuid party FK; string posting_status; string payment_status }
    TreasuryAccount { uuid id PK "[S06]"; uuid company FK; string kind "CASH/BANK (ADR-022)"; uuid gl_account FK; string bank_name; string account_number }
    Payment { uuid id PK "[S06]"; uuid company FK; string direction "RECEIPT/PAYMENT"; uuid party FK; uuid treasury_account FK; string method "CASH/BANK_TRANSFER/CHEQUE"; decimal amount ">0"; string status "DRAFT/POSTED/REVERSED"; uuid counterparty_account FK "AR/AP used at posting"; uuid journal_entry FK }
    PaymentAllocation { uuid id PK "[S06]"; uuid payment FK; uuid sales_invoice FK "nullable, exactly one target"; uuid purchase_invoice FK "nullable"; decimal amount ">0"; string status "ACTIVE/VOID (ADR-025)" }
    Cheque { uuid id PK "[S06]"; uuid company FK; string direction "RECEIVED/ISSUED"; uuid payment FK; string cheque_number "UK per company+direction+bank"; string sayad_id; decimal amount ">0"; date due_date; string status "state machine (ADR-026)"; uuid holding_account FK }
    Payment { uuid id PK "[planned]"; decimal amount; date payment_date }
    PaymentAllocation { uuid id PK "[planned]"; uuid payment FK; decimal amount }
    Cheque { uuid id PK "[planned]"; date due_date; string status }
```

## Integrity notes
- Referential integrity: FKs use CASCADE inside a company aggregate
  (branches, periods, memberships), PROTECT for account parents (history
  must not vanish), SET_NULL for audit actors.
- Cross-company FK consistency cannot be expressed as a plain DB
  constraint for all pairs; it is enforced by application services +
  tests (Sprint 01 covers account parent and fiscal period company).
- Transaction boundaries: posting operations (journal, invoice, stock)
  are each one `atomic` service call (journal since S02, stock since S03,
  purchase invoice/return posting — stock + journal together — since S04).
