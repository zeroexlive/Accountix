# Product Requirements Document — Accountix

Status: v0.1, 2026-11-02. Anything marked **Planned** does not exist yet.

## 1. Executive summary
Web-based, offline-first accounting + inventory application for SMEs,
with a real double-entry engine under a simple UI. Sprint 01 delivers only
the foundation (auth, companies, fiscal calendar, chart of accounts).

## 2. Product vision
Financial correctness of professional accounting software, simplicity of a
modern web app, reliability of a desktop app, scalability of Django.

## 3. Target market
Initial: Iran (Persian RTL UI, IRR, Jalali display, cheque workflows).
Future: international — localization and currency are configuration, not
code paths embedded in calculations.

## 4. User personas
Accountant, financial manager, business owner, trading company operator,
sales/purchasing operators, warehouse manager, cashier, system admin.

## 5. Business problems
Spreadsheet accounting with no audit trail; inventory quantities that do
not reconcile with money; multi-user tools that require constant internet;
Iranian businesses needing Jalali/IRR/cheque support without enterprise cost.

## 6. Functional requirements (by module)
- Organizations: companies, branches, memberships/roles, fiscal years/periods. **[Sprint 01: implemented, except role enforcement]**
- Accounting: chart of accounts **[Sprint 01: initial model]**; journal
  entries, posting, reversal, GL, trial balance, statements. **Planned**
- Parties, catalog, inventory (ledger + moving weighted average), sales,
  purchasing, treasury/cheques, reporting/PDF/Excel. **All Planned**

## 7. Non-functional requirements
Offline-first local mode (SQLite), LAN/cloud mode (PostgreSQL), Decimal
money only, company isolation, auditability, atomic posting, idempotency,
responsive accessible UI, documented backup/restore.

## 8. User stories (examples)
- As an owner, I create a company and become its OWNER automatically.
- As an accountant, I define fiscal years that cannot overlap.
- As an accountant, I build a chart of accounts where codes are unique per
  company and parent cycles are impossible. *(all Sprint 01, tested)*
- As an accountant, I post a balanced journal entry that cannot be edited
  silently afterwards. *(Planned, Sprint 02)*

## 9. Acceptance criteria
Per-phase quality gates in the master prompt §25: tests pass, lint passes,
migrations valid, docs updated, no secrets committed. Financial features
additionally: invariants, isolation, atomicity, reconciliation tests.

## 10. MVP definition — Internal MVP
First integrated version completing a real purchase→sale workflow:
foundation + accounting engine + inventory engine + purchasing + sales
(Phases 1–5 of the roadmap). **Not reached yet.**

## 11. Version 1.0 scope — Commercial v1.0
Internal MVP plus treasury/cheques, advanced inventory, reporting,
desktop packaging (Windows/Linux launchers), production hardening,
backup/restore verification. v1.0 must satisfy
`docs/engineering/RELEASE_READINESS.md` (to be created in Phase 10).

## 12. Future roadmap
Phases 0–10 per the master prompt §23. Current position: Phase 0 done,
Phases 1-5 (Sprints 01-05) done; the Internal MVP workflow of §10/§20.4 passes end-to-end as of Sprint 05. Phase 6 (treasury) next. Internal MVP is not commercial v1.0.

## 13. Security requirements
Auth + company-level authorization, CSRF, secure sessions, env-only
secrets, audit events, OWASP-aligned input/output handling, cross-company
leakage tests.

## 14. Performance requirements
Indexed FKs/codes, pagination on all lists, no N+1 on list views
(`select_related` used in Sprint 01), aggregation queries for reports,
profiling before optimization.

## 15. Localization strategy
Django i18n; `fa` default, `en` prepared; dates stored Gregorian/UTC,
displayed Jalali when Persian is active (Planned — not implemented);
amounts stored in the company currency (default IRR), toman only as a
display conversion.

## 16. Deployment strategy
Local (launcher + SQLite + Waitress), LAN (PostgreSQL), cloud (reverse
proxy + HTTPS + PostgreSQL). Django dev server is never a production server.

## 17. Risks and dependencies
Tax/e-invoicing regulation changes in Iran (verify before claiming
compliance); Python 3.13 verification pending; single-machine development;
GitHub push via connector is file-based (large trees are slow).

## 18. Release acceptance criteria
§29 of the master prompt: reconciled reports, E2E workflows, security +
concurrency tests, backup/restore proof, working Windows/Linux installs,
accurate docs. **None of these are claimed for Sprint 01.**
