# Architecture Decision Records

## ADR-001 — Modular monolith (accepted)
Single deployable Django application organized by business domain. No
microservices until a demonstrated requirement exists (master prompt §5.1).

## ADR-002 — Service layer for cross-record rules (accepted)
Overlap, hierarchy/cycle and (later) posting rules live in per-app
`services.py`, invoked from model `clean()` and views/forms. Views, templates
and signals contain no complex business logic (§5.3).

## ADR-003 — SQLite local / PostgreSQL production via DATABASE_URL (accepted)
Default is a SQLite file at the project root (or `ACCOUNTIX_DATA_DIR`);
a `postgres://` `DATABASE_URL` switches engines. Parser is hand-rolled in
`config/settings/base.py` to avoid an extra dependency for two backends.

## ADR-004 — FiscalYear/FiscalPeriod live in `organizations` (accepted)
They are company-scoped master data; `accounting` consumes them from
Sprint 02. Alternative (accounting) was considered; organizations avoids a
circular dependency because accounting already depends on Company.

## ADR-005 — Account posting flag named `is_postable` (accepted)
Prompt wording "posting eligibility" is implemented as `is_postable`
(default False: an account must be explicitly made postable).

## ADR-006 — No Tailwind/HTMX/Alpine CDN (accepted, temporary)
Offline-first (§16) forbids depending on a CDN at runtime. Sprint 01 ships a
small hand-written CSS file. Tailwind and HTMX/Alpine will be **vendored**
locally in a later sprint; until then the UI is server-rendered only.

## ADR-007 — Python >=3.12 locally, 3.13 targeted (accepted with caveat)
This development machine provides Python 3.12.3 only. Django 5.2 LTS supports
it. 3.13 must be added to CI before any 3.13 support claim (see CURRENT_STATE TD-4).

## ADR-008 — Money is Decimal, currency is ISO 4217 (accepted)
Default company currency `IRR`. Toman is a display unit (1 toman = 10 rials)
with explicit conversion at presentation time — never a stored currency.
