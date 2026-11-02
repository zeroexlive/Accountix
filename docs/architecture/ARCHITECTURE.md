# Architecture

## Style
Modular monolith (master prompt §5): one Django deployable, modules by
business domain, four conceptual layers — Presentation (views/templates/API),
Application (services: use cases, transactions, authorization), Domain
(rules/invariants in services + model validation), Infrastructure (ORM,
settings, logging). No generic repository layer; Django ORM is used directly.

## Module map (backend/apps/)
| App | Status | Responsibility |
|---|---|---|
| core | Implemented S01 | Base model, company-access helpers, dashboard, health |
| users | Implemented S01 | Custom user model (UUID pk) |
| organizations | Implemented S01 | Company, Branch, CompanyMembership, FiscalYear, FiscalPeriod |
| accounting | Partial S01 | Account only; journal engine is Sprint 02 |
| audit | Implemented S01 | AuditEvent + record_event helper |
| parties, catalog, inventory, sales, purchases, treasury, reporting | Planned placeholders | Not installed, no models |

Dependency direction: accounting → organizations → core; audit →
organizations/core; nothing imports "upwards". No circular imports.

## Data & transactions
UUID PKs, Decimal money (future fields), per-company unique constraints.
Business operations that span records will run in `transaction.atomic`
service functions (the pattern is established by fiscal/account validation
services in Sprint 01). `select_for_update` semantics differ on SQLite —
concurrency guarantees are only claimed on PostgreSQL and only after tests.

## Deployment modes
Local: launcher (Planned) → Waitress → SQLite → browser.
LAN: browser clients → Django → PostgreSQL.
Cloud: HTTPS reverse proxy → Django → PostgreSQL.
Two-way offline sync between independently writable DBs is out of scope.

## Frontend
Django templates, RTL Persian default, server-rendered in Sprint 01.
Tailwind/HTMX/Alpine are planned to be vendored locally (ADR-006).
