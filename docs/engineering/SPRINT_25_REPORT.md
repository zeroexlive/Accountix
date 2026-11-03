# Sprint 25 Report — Role-Permission Enforcement (ADR-050)

Date: 2026-11-03. Environment: Linux, Python 3.12.3, Django 5.2,
gettext 0.21 present. Base: Sprint 24 complete (384 tests; bundle
current through Sprint 24). This sprint closes CURRENT_STATE §10
item 5: `CompanyMembership` roles existed since Sprint 01 but no
operation checked them — any member of a company, VIEWER included,
could do everything in it. Full rationale and the matrix:
**ADR-050**.

## The role set and the matrix

`CompanyMembership.Role` (organizations, unchanged): OWNER
"Owner", ADMIN "Admin", ACCOUNTANT "Accountant", SALES "Sales
operator", PURCHASES "Purchasing operator", WAREHOUSE "Warehouse
manager", CASHIER "Cashier", VIEWER "Viewer". **Field default:
VIEWER** (the least-privilege choice, already in the model).
Membership also carries `is_active`; inactive memberships confer
nothing (they were already excluded from every scoped queryset).

| Operation class | OWNER | ADMIN | ACCOUNTANT | SALES | PURCHASES | WAREHOUSE | CASHIER | VIEWER |
|---|---|---|---|---|---|---|---|---|
| READ — lists, details, dashboard, reports, exports, print | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| OPERATE — create/edit drafts, post/reverse documents, payments + allocations, cheque actions, stock documents + counts, statement import + matching, master data (parties, products, units, categories, warehouses, cheque books) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| ADMINISTER — fiscal period close/reopen, fiscal year close, fiscal year creation, opening balances, chart of accounts, treasury accounts | ✓ | ✓ | — | — | — | — | — | — |
| GOVERN — membership management (no UI exists; see Partially) | ✓ | — | — | — | — | — | — | — |

Tier placement notes: bank-statement completion/reopen sit in
OPERATE (daily reconciliation work, per the sprint brief's tier
definition); cheque-book creation is OPERATE while the
GL-linked treasury *account* is ADMINISTER (structure, like the
chart of accounts). Company creation is global, not per-company,
and stays ungated — the creator becomes OWNER of the new company.
No company-settings edit page exists, so nothing maps to that
cell yet (ADR-050 (5)).

## Implemented

### Enforcement core — `apps/core/access.py` (one helper home)

- Tier constants `READ_/OPERATE_/ADMINISTER_/GOVERN_ROLES` as
  plain role-value tuples (keeps the module import-cycle free,
  the codebase's existing style); a unit test pins them against
  `CompanyMembership.Role` so tiers and choices cannot drift.
- `membership_for(user, company)` — the ACTIVE membership or
  None, cached on the user instance (user objects live exactly
  one request, so the view gate, context processor and template
  tags share one query). `role_for` on top of it.
- `require_company_role(user, company, roles)` — raises
  `PermissionDenied`. `require_posted_company_role(request,
  roles)` — the Sprint 12 posted-company rule extended: foreign
  company id 404s first, then the role check 403s.
  `scoped_company_role_required(*roles)` — decorator for the
  `resolve_scoped_company` create views; it resolves the company
  exactly as the view will and gates when one is resolved (an
  unresolved multi-company chooser can only render, never save —
  ADR-050 (1)).

### Company-resolution patterns supported (inventoried, all covered)

1. **Object-based** (dominant): the view fetches its object with
   `company_id__in=user_company_ids(user)` (non-member → 404),
   then one line `require_company_role(request.user, obj.company,
   TIER)`.
2. **Scoped create** via `resolve_scoped_company` (POST → GET →
   single-membership default): the decorator.
3. **Form-carried company**: the check runs on
   `form.cleaned_data["company"]` after `is_valid()`
   (account_create, fiscal_year_create).
4. **Posted-company master data** (party/unit/category/warehouse
   create): `require_posted_company_role`.

### Endpoints gated — 55 mutating endpoints

- OPERATE (48): accounting journal create/post/reverse (3);
  parties create/edit (2); inventory product create/edit, unit/
  category/warehouse create, count create/save/post/reverse,
  stock document create/post/reverse (12); purchases invoice
  create/post/reverse + return create/post/reverse (6); sales
  same (6); treasury payment create/post/allocate/reverse,
  allocation void, cheque deposit/clear/bounce/return,
  cheque book create, cheque leaf void, bank statement create +
  add-line/import/auto-match/match/unmatch/complete/reopen (19).
- ADMINISTER (7): fiscal year create, fiscal period close,
  fiscal period reopen, fiscal year close (organizations);
  opening balance create, account create (accounting);
  treasury account create (treasury).
- Read endpoints: untouched — membership only, as before.
  Reporting endpoints are GET exports only; nothing mutates.

### Defense in depth in services

`apps/accounting/services.py` gained `_require_administer_role`,
asserted at the top of the four ADMINISTER services that take
`user=`: `post_opening_balance`, `close_fiscal_period`,
`reopen_fiscal_period`, `close_fiscal_year`. It raises
`PermissionDenied` — deliberately not `ValidationError`, so the
views' `except ValidationError` handling can never soften it
into a form error. `user=None` stays the trusted internal path
(the user-less service API predates the UI; the web layer always
passes the user and is itself gated). `close_fiscal_year`'s
internal call to `close_fiscal_period` re-checks with the same
user — consistent by construction.

### Denied behavior

A member below the tier gets HTTP 403 rendering the new
`templates/403.html` — a Persian page in the app shell ("دسترسی
مجاز نیست" + explanation + back-to-dashboard). Ordering is the
invariant: membership scoping runs first everywhere, so a
non-member still gets 404 exactly as today and can never learn
from a 403 that a company or object exists. New strings wrapped
per ADR-045/046 and translated: catalogs are now 1041 msgids,
en 100% (0 empty, 0 fuzzy per `msgattrib`), `msgfmt --check`
clean for both catalogs; fa msgstrs stay empty by design.

### UI surfacing (presentation only)

- `apps/core/context_processors.company_roles` (registered in
  base settings): `company_roles` (company pk → role),
  `primary_membership`, `can_operate_anywhere`,
  `can_administer_anywhere`.
- Shell: the sidebar user block now shows *company name · role
  label* (the catalogued choice label, e.g. «مالک») for the
  primary membership, with the previous «کاربر سیستم» label as
  the fallback for membership-less users.
- `apps/core/templatetags/access_tags.py`: `company_role` and
  `company_can(company, tier)`. Action forms/buttons are hidden
  from roles that cannot use them on 12 detail templates
  (journal, sales/purchase invoice + return, payment, cheque,
  bank statement, cheque book, stock count, stock document,
  fiscal year — the last at ADMINISTER) and create buttons on
  13 list templates + the sidebar's opening-balance link
  (ADMINISTER). The server gates remain authoritative; tests
  prove POST denial with the button hidden.

## Tested

- **New module `apps/core/tests/test_role_permissions.py` —
  24 tests**: tier pinning vs the model + the VIEWER default;
  inactive membership confers no role; reads return 200 for all
  8 roles (parametrized); viewer OPERATE POSTs (journal create,
  journal post, party create) → 403 with the Persian page and
  **nothing persisted**; OPERATE passes for
  ACCOUNTANT/SALES/CASHIER/WAREHOUSE (parametrized); ACCOUNTANT
  ADMINISTER denials (fiscal year create, period-close page on
  GET and by construction POST, account create) with nothing
  persisted; OWNER/ADMIN administer passes; service-layer
  `PermissionDenied` for close/opening-balance/reopen with an
  operate-tier user, success with an ADMINISTER user and with
  `user=None`; non-member 404 on read **and** write;
  **cross-company proof** — one user, OWNER of company A and
  VIEWER of company B, posts in A and is 403-denied in B while
  still reading it; the Sprint 24 setup-created admin (OWNER)
  administers unaffected; button-hiding spot checks (viewer
  lacks the journal-post form action, the invoice-create href
  and the period-close href that the owner/admin sees) alongside
  the POST-denial proofs; shell role-label rendering («مالک» +
  company name; fallback label without memberships).
- **Full suite: 408 passed + 3 skipped** (baseline 384 + 3, plus
  the 24 new) — zero regressions.
- **Fixture changes: 0.** The brief anticipated that world
  builders modelling writers might need upgrading to OWNER;
  the inventory found every UI test builder already creates
  OWNER memberships, the three ACCOUNTANT memberships in the
  suite are read-isolation tests (and ACCOUNTANT is OPERATE
  tier anyway), and the one default-role membership is a
  unique-constraint model test that touches no gated endpoint.
  Nothing had to change, and the matrix was not weakened.
- Gates (exact commands, all from `backend/` unless noted):
  `.venv/bin/python -m pytest` → 408 passed, 3 skipped;
  `manage.py check` under `config.settings.local`, `.test`,
  `.standalone`, `.postgres_test` → no issues; under
  `.production` (with `DJANGO_SECRET_KEY` set, as that module
  requires by design) → no issues;
  `manage.py makemigrations --check --dry-run` → "No changes
  detected"; `mypy --config-file ../pyproject.toml .` →
  Success, 184 files; `ruff check .` → all checks passed;
  `ruff format --check .` → 184 files already formatted;
  `msgfmt --check` on both catalogs → clean.

## Partially implemented

- **GOVERN tier**: defined, pinned by test, and documented —
  but it gates nothing, because there is no membership
  management UI to gate (organizations URLs carry no member
  pages). Membership assignment remains the Django admin,
  which is the operator's own tool and out of scope for
  product roles (ADR-050 (5)). No surface was invented to
  have something to gate.
- **UI surfacing depth**: action-hiding covers the detail and
  list templates listed above; form *pages* themselves are not
  hidden (they are gated server-side instead — an under-roled
  member following a stale link gets the 403 page, which is
  the designed behavior).

## Planned (follow-ups)

- **Members UI** (the GOVERN follow-up): per-company member
  list with invite/role-change/remove, gated GOVERN, with
  the last-OWNER guard in the service/form layer (an owner
  cannot demote/remove the company's final OWNER, and a
  non-owner can never touch an OWNER row).
- **Bundle rebuild**: the PyInstaller bundle is current
  through Sprint 24; Sprint 25's code (403 page, context
  processor, template tags) needs the next bundle rebuild +
  frozen smoke, on the Sprint 23/24 pattern.
- Windows bundle verification — unchanged, still the only
  NOT VERIFIED release-gate item; needs a Windows machine.

## Blocked

- Nothing blocked this sprint. No model changes were needed
  (role choices and the VIEWER default were already right),
  so there is no migration; Jason runs nothing after pulling
  beyond the standing `compilemessages` for dev checkouts.
