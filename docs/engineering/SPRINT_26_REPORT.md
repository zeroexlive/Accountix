# Sprint 26 Report — Members UI (GOVERN) + Bundle Rebuild (ADR-051)

Date: 2026-11-03. Environment: Linux, Python 3.12.3, Django 5.2,
gettext 0.21 present. Base: Sprint 25 complete (408 tests; bundle
current through Sprint 24). Two parts, in order: (1) the members
UI that ADR-050 (5) left as the GOVERN follow-up — the tier was
defined and pinned but gated nothing, because no members page
existed; (2) a PyInstaller bundle rebuild + frozen smoke so the
shipped binary carries Sprints 24+25+26. Full rationale:
**ADR-051**.

## Implemented

### Part 1 — Members UI (organizations app)

- **Routes** (company scope, mirroring the organizations URL
  style): `companies/<pk>/members/` (page) plus POST actions
  `members/add-existing/`, `members/add-new/`,
  `members/<member_pk>/role/`, `…/deactivate/`, `…/reactivate/`.
  Every view resolves the company/gating through one helper pair
  with the ADR-050 ordering: the company fetch is membership-
  scoped (non-member → 404), then `require_company_role(…,
  GOVERN_ROLES)` (member below OWNER → 403, the Persian 403
  page). Action views fetch the membership company-scoped, so a
  membership id from another company 404s for everyone.
- **The page**: roster table (username + full name, catalogued
  role label, active status, `created_at` through the `jalali`
  filter as the joined date, per-row actions) in design system
  v2, fully server-rendered — a role `<select>` form and a
  deactivate/reactivate form per row, no JS dependency. Inactive
  rows stay visible with a reactivate action. The members link
  appears only for OWNERs: on the company detail page and in
  company-list rows, both via the Sprint 25 `company_can`
  template tag at the GOVERN tier.
- **Add path (a) — attach existing**: `AttachMemberForm` takes an
  exact username + role. Unknown username → field error
  («کاربری با این نام کاربری یافت نشد.»); already a member →
  field error; invalid role → choice error. No email invites —
  the product is offline-first (ADR-051 (1)).
- **Add path (b) — create new inline**: `CreateMemberUserForm`, a
  `UserCreationForm` subclass (the Sprint 24 setup pattern,
  ADR-049) with first/last name + role. The full
  AUTH_PASSWORD_VALIDATORS set and the username-uniqueness check
  run as form validation: a weak password or a taken username
  creates nothing. The service then creates the user and the
  membership in one transaction; the user gets no staff/superuser
  flags (authority is the membership alone) and can log in
  immediately.
- **Services with the guards inside** (`apps/organizations/
  services.py`): `add_member`, `create_member`,
  `change_member_role`, `deactivate_member`, `reactivate_member`.
  Each takes the actor and re-asserts GOVERN itself via
  `_require_govern_role` — PermissionDenied, `actor=None` the
  trusted internal path, exactly the ADR-050 (3) posture.
  `add_member` repeats the already-member check so the model's
  unique constraint can never surface as an IntegrityError (a
  deactivated member is reactivated, never re-added).
- **Last-owner guard**: demoting or deactivating a membership
  that is the company's sole remaining ACTIVE OWNER raises a
  `ValidationError` (Persian message, catalogued) and persists
  nothing. The count excludes the target row, so self-targeting
  is guarded identically; with ≥2 active owners both operations
  are allowed (ADR-051 (3)).
- **Deactivation is the removal path** — no hard delete anywhere:
  the row stays for history/audit, and because every scoped
  queryset and role lookup sees ACTIVE memberships only, access
  ends with the flip (ADR-051 (4)).
- **i18n**: 31 new msgids, additive only (semantic po diff: 0
  removed, 0 altered besides the header timestamp; a second
  `makemessages` run is a fixpoint). fa keeps the Persian-literal
  msgids empty by convention and gained Persian msgstrs for the
  3 English-source service messages; xgettext's fuzzy guesses in
  en were all replaced with the real translations — en is
  1072/1072 translated, 0 fuzzy, `msgfmt --check` clean on both
  catalogs. Catalogs now hold 1072 msgids.

### Part 2 — Bundle rebuild

- `scripts/build_linux.sh` as shipped, exit 0. **No spec or
  script changes were needed**: the members UI is project code
  and templates (already collected/shipped as data), and the
  Sprint 23 axes fix is intact. Bundle: **116 MB, 3,832 files**
  (Sprint 24: 116 MB, 3,830) at `dist/accountix/` (gitignored,
  never synced).
- **Spec audit of the output**: `_internal/templates/
  organizations/company_members.html` and `templates/403.html`
  present as data files; `_internal/locale/{fa,en}/LC_MESSAGES/
  django.mo` compiled and shipped; the PYZ census counts 2,308
  entries including `axes` (41 entries, 11 migration modules,
  `axes.middleware` + `axes.backends` present) and the new
  `apps.organizations` services/views/forms modules.

## Tested

- **New module `apps/organizations/tests/test_members_ui.py` —
  22 tests**: the roster renders for the OWNER (usernames, fa
  role labels, both add forms); GOVERN gating — ADMIN/ACCOUNTANT/
  VIEWER members get 403 on the page, an ADMIN's add/role/
  deactivate POSTs are 403 and persist nothing, a non-member gets
  404; attach-existing happy path + unknown username + already-
  member + deactivated-member re-add (form error, one row) +
  invalid role; create-new happy path with a **real login POST**
  by the created user (and no staff/superuser flags), weak
  password `1234` rejected by the validators with zero rows
  created, duplicate username a form error; **immediate effect** —
  an ACCOUNTANT's journal-create POST returns 302, the OWNER
  demotes them to VIEWER through the UI, the identical POST then
  returns 403 with no second entry; **last-owner guard** — sole
  owner self-demote and self-deactivate refused (row unchanged),
  two-owner demote + deactivate allowed; service-layer proofs —
  the guard raises `ValidationError`, a non-OWNER actor raises
  `PermissionDenied`, `actor=None` works as the trusted path;
  **deactivation cuts access** — the member's company-detail GET
  goes 200 → 404 on deactivation and back to 200 on
  reactivation, role preserved; cross-company — another company's
  members page 404s and its membership id under this company's
  URL 404s with the row untouched.
- **Full suite: 430 passed + 3 skipped** (baseline 408 + 3, plus
  the 22 new) — zero regressions, and zero fixture changes.
- **Frozen smoke** (fresh data dir `/tmp/s26/data`, port 8879,
  curl, bundle binary only):

  | Step | Result |
  |---|---|
  | Launch (fresh dir) | health 200; server up in-process (frozen mode) |
  | GET /login/ (zero users) | 302 → /setup/ |
  | GET /setup/ | 200, `lang="fa" dir="rtl"` |
  | POST /setup/ (admin + `Smoke Co`) | 302 → / |
  | GET / (dashboard) | 200, company shown |
  | GET /organizations/companies/ | 200; the OWNER-only members link present (pk extracted from it) |
  | GET members page (OWNER) | 200; roster + «افزودن عضو موجود» + «ساخت کاربر جدید» sections render (Persian from the bundled .mo) |
  | POST add-new (`viewer2`, role VIEWER) | 302 → members page; roster now lists viewer2 |
  | viewer2 POST /login/ (fresh jar) | 302 → /; dashboard 200; journal list 200 (READ works) |
  | viewer2 POST journal create | **403** with the Persian «دسترسی مجاز نیست» page (OPERATE enforced, frozen) |
  | viewer2 GET members page | **403** (GOVERN enforced, frozen) |
  | Server stop | port closed cleanly |
  | `accountix manage --data-dir … check` (frozen) | "System check identified no issues", **exit 0** |
  | DB inspection | 48 migrations applied by the bundle; users: admin (staff=1, superuser=1) + viewer2 (0, 0); memberships: admin OWNER active, viewer2 VIEWER active |

- Gates (exact commands, from `backend/` unless noted):
  `.venv/bin/python -m pytest` (repo root) → 430 passed,
  3 skipped; `manage.py check` under `config.settings.local`,
  `.test`, `.standalone`, `.postgres_test` → no issues; under
  `.production` (with `DJANGO_SECRET_KEY` set, as that module
  requires by design) → no issues;
  `manage.py makemigrations --check --dry-run` → "No changes
  detected" (**no model changes this sprint — no migration**;
  the roster's joined date is the existing `created_at` from the
  shared timestamp base, a deliberate use-what-exists choice);
  `mypy --config-file ../pyproject.toml .` → Success, 185 files;
  `ruff check .` → all passed; `ruff format --check .` → 185
  files already formatted; `msgfmt --check` on both catalogs →
  clean.

## Partially implemented

- Nothing partial in the brief's scope. Accepted boundaries,
  documented in ADR-051 (5): the Django admin can still edit
  memberships directly (the operator's own tool, outside product
  roles); member password resets stay an operator task via the
  launcher's `manage changepassword` passthrough; there is no
  self-service profile/password page yet.

## Planned (follow-ups)

- **Self-service account surface**: a signed-in user's own
  profile + password-change page (today: admin/launcher only).
- **Role-scoped dashboards** (optional polish): the dashboard
  still shows the same summary to every role; nothing in the
  tier model requires it, but a VIEWER-specific read-only
  landing could reduce noise.
- Windows bundle verification — unchanged, still the only
  NOT VERIFIED release-gate item; needs a Windows machine.

## Blocked

- Nothing blocked this sprint. No sync blockers expected: the
  change set is code/templates/catalogs/docs only (dist/ and
  .venv-build/ are gitignored), and the end-of-sprint sync rides
  the established one-commit `github push-files` route.
