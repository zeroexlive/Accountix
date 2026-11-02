# Entity Relationship Diagram

Legend: **[S01]** = implemented with migrations in Sprint 01.
**[planned]** = full target schema from the master prompt §13.2; no model
exists yet. All planned entities will carry `id (UUID PK)`, `created_at`,
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

    Company ||--o{ Party : "[planned] owns"
    Party ||--o{ PartyContact : "[planned]"
    Party ||--o{ PartyAddress : "[planned]"
    Company ||--o{ ProductCategory : "[planned]"
    ProductCategory ||--o{ Product : "[planned]"
    Unit ||--o{ ProductUnitConversion : "[planned]"
    Product ||--o{ ProductUnitConversion : "[planned]"
    Product ||--o{ ProductPrice : "[planned]"
    Company ||--o{ Warehouse : "[planned]"
    Warehouse ||--o{ StockMovement : "[planned]"
    Product ||--o{ StockMovement : "[planned]"
    StockDocument ||--o{ StockDocumentLine : "[planned]"
    StockDocument ||--o{ StockMovement : "[planned] generates"
    Warehouse ||--o{ StockBalance : "[planned]"
    Product ||--o{ StockBalance : "[planned]"
    InventoryCount ||--o{ InventoryCountLine : "[planned]"
    FiscalPeriod ||--o{ JournalEntry : "[planned] period of"
    JournalEntry ||--o{ JournalLine : "[planned]"
    Account ||--o{ JournalLine : "[planned] posted to"
    JournalEntry ||--|| JournalReversal : "[planned] reversed by"
    Party ||--o{ SalesInvoice : "[planned] customer"
    SalesInvoice ||--o{ SalesInvoiceLine : "[planned]"
    Product ||--o{ SalesInvoiceLine : "[planned]"
    SalesQuotation ||--o{ SalesInvoice : "[planned] converts to"
    Party ||--o{ PurchaseInvoice : "[planned] supplier"
    PurchaseInvoice ||--o{ PurchaseInvoiceLine : "[planned]"
    PurchaseOrder ||--o{ PurchaseInvoice : "[planned] fulfilled by"
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
    JournalEntry { uuid id PK "[planned]"; uuid company FK; uuid period FK; date entry_date; string status; uuid reversal_of FK "nullable" }
    JournalLine { uuid id PK "[planned]"; uuid entry FK; uuid account FK; decimal debit; decimal credit }
    Product { uuid id PK "[planned]"; string sku "UK per company"; string barcode; bool is_stockable }
    StockMovement { uuid id PK "[planned]"; uuid warehouse FK; uuid product FK; decimal quantity_change; decimal value_change }
    StockBalance { uuid id PK "[planned]"; uuid warehouse FK; uuid product FK; "UK(warehouse,product)" x }
    SalesInvoice { uuid id PK "[planned]"; uuid party FK; string posting_status; string payment_status }
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
  will each be one `atomic` service call — Planned.
