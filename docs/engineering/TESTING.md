# Testing Strategy

Implemented in Sprint 01: pytest + pytest-django, settings
`config.settings.test` (in-memory SQLite). 25 tests — auth (5),
organizations/fiscal validation & isolation (11), accounts (7),
core health/audit (2). Run: `.venv/bin/python -m pytest` from repo root.

Principles (master prompt §20): tests assert business outcomes, never
weakened to pass; results are reported with exact commands/counts in the
sprint report; unrun tests are reported as unrun.

Planned and **not yet present**: integration suite for posting workflows,
PostgreSQL concurrency tests (duplicate posting, concurrent stock issues,
document numbering), end-to-end purchase→sale→payment workflow, security
suite (unauthorized access / cross-company leakage beyond the Sprint 01
view tests), coverage measurement in CI. Locations reserved under
`tests/{unit,integration,functional,security}/`.
