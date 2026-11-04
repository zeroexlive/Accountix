import hashlib
import json
import secrets
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.access import (
    OPERATE_ROLES,
    require_company_role,
    resolve_scoped_company,
    user_company_ids,
)
from apps.core.models import ScanSession, ScanSubmission
from apps.organizations.models import Company


def health(request):
    return JsonResponse({"status": "ok"})


@login_required
def dashboard(request):
    """The one dashboard route (core) rendering the reporting app's
    aggregation (Sprint 08): ``apps.reporting.services.dashboard_data``
    derives every card from the owning apps' reports — core keeps the
    URL, reporting owns the figures; there is no second dashboard."""
    from apps.reporting.services import dashboard_data

    companies = Company.objects.filter(id__in=user_company_ids(request.user), is_active=True)
    company = None
    data = None
    company_id = request.GET.get("company")
    if company_id:
        company = get_object_or_404(companies, pk=company_id)
    elif companies:
        company = companies.first()
    if company is not None:
        data = dashboard_data(company)
    return render(
        request,
        "core/dashboard.html",
        {"companies": companies, "company": company, "dashboard": data},
    )


# ---------------------------------------------------------------------------
# Barcode / QR scanning in invoicing (Sprint 31, ADR-060)
# ---------------------------------------------------------------------------

SCAN_SESSION_TTL = timedelta(minutes=10)
SCAN_MAX_SUBMISSIONS_PER_SESSION = 120
SCAN_MAX_LIVE_SESSIONS_PER_USER = 3


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve_scan_product(company, code):
    """The one scan resolution rule: exact barcode match inside the
    company first, then exact SKU. Active products only. Returns
    None for anything else — a scan can never reach another
    company's catalog."""
    from apps.catalog.models import Product

    code = (code or "").strip()
    if not code:
        return None
    return (
        Product.objects.filter(company=company, barcode=code, is_active=True)
        .select_related("base_unit")
        .first()
        or Product.objects.filter(company=company, sku=code, is_active=True)
        .select_related("base_unit")
        .first()
    )


def _money(value):
    return format(value, "f") if value is not None else None


def scan_product_payload(product):
    return {
        "id": str(product.pk),
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "unit_id": str(product.base_unit_id),
        "unit_label": str(product.base_unit),
        "sale_price": _money(product.default_sale_price),
        "purchase_price": _money(product.default_purchase_price),
    }


@login_required
def scan_lookup(request):
    """GET ?code=&company= → the product a scan resolves to.

    Login + OPERATE tier in the resolved company (a foreign company
    id 404s inside the resolver, per the standing scoping rule)."""
    _companies, company = resolve_scoped_company(request)
    if company is None:
        return JsonResponse({"error": gettext("شرکتی انتخاب نشده است.")}, status=400)
    require_company_role(request.user, company, OPERATE_ROLES)
    product = resolve_scan_product(company, request.GET.get("code", ""))
    if product is None:
        return JsonResponse(
            {"error": gettext("کالایی با این کد یافت نشد.")}, status=404
        )
    return JsonResponse(scan_product_payload(product))


@login_required
@require_POST
def scan_session_create(request):
    _companies, company = resolve_scoped_company(request)
    if company is None:
        return JsonResponse({"error": gettext("شرکتی انتخاب نشده است.")}, status=400)
    require_company_role(request.user, company, OPERATE_ROLES)
    live = ScanSession.objects.filter(
        created_by=request.user, revoked=False, expires_at__gt=timezone.now()
    ).count()
    if live >= SCAN_MAX_LIVE_SESSIONS_PER_USER:
        return JsonResponse(
            {"error": gettext("نشست‌های اسکن فعال زیادی دارید؛ یکی را قطع کنید.")},
            status=429,
        )
    raw = secrets.token_urlsafe(32)
    session = ScanSession.objects.create(
        token_hash=_hash_token(raw),
        company=company,
        created_by=request.user,
        expires_at=timezone.now() + SCAN_SESSION_TTL,
    )
    return JsonResponse(
        {
            "session_id": str(session.pk),
            "phone_url": request.build_absolute_uri(
                reverse("scan_phone_page", args=[raw])
            ),
            "results_url": reverse("scan_session_results", args=[session.pk]),
            "revoke_url": reverse("scan_session_revoke", args=[session.pk]),
            "expires_at": session.expires_at.isoformat(),
        }
    )


@login_required
def scan_session_results(request, pk):
    """Desktop poll: each queued submission is returned exactly
    once (marked consumed in the same transaction)."""
    session = get_object_or_404(ScanSession, pk=pk, created_by=request.user)
    with transaction.atomic():
        subs = list(
            session.submissions.filter(consumed=False).select_related(
                "product", "product__base_unit"
            )
        )
        if subs:
            ScanSubmission.objects.filter(pk__in=[s.pk for s in subs]).update(
                consumed=True
            )
    return JsonResponse(
        {
            "live": session.is_live(),
            "results": [
                {"code": s.code, "product": scan_product_payload(s.product)}
                for s in subs
            ],
        }
    )


@login_required
@require_POST
def scan_session_revoke(request, pk):
    session = get_object_or_404(ScanSession, pk=pk, created_by=request.user)
    session.revoked = True
    session.save(update_fields=["revoked", "updated_at"])
    return JsonResponse({"ok": True})


def _session_for_token(raw):
    return (
        ScanSession.objects.filter(token_hash=_hash_token(raw))
        .select_related("company", "created_by")
        .first()
    )


def scan_phone_page(request, token):
    """The phone side of a pairing. No login: the unguessable
    token (only its hash is stored) is the credential, and the
    page exposes nothing but the company name and who paired it."""
    session = _session_for_token(token)
    if session is None or not session.is_live():
        raise Http404
    creator = session.created_by
    return render(
        request,
        "core/scan_phone.html",
        {
            "company_name": session.company.name,
            "creator_name": creator.get_full_name() or creator.username,
            "submit_url": reverse("scan_phone_submit", args=[token]),
            "expires_at": session.expires_at,
        },
    )


@csrf_exempt
@require_POST
def scan_phone_submit(request, token):
    """Phone submits a scanned/typed code. CSRF-exempt BY DESIGN
    (ADR-060): the phone holds no session cookie to protect — the
    URL token is the credential — and the endpoint is bounded by
    the session's liveness, the per-session submission cap, and
    server-side product resolution inside the bound company."""
    session = _session_for_token(token)
    if session is None or not session.is_live():
        raise Http404
    if session.submissions.count() >= SCAN_MAX_SUBMISSIONS_PER_SESSION:
        return JsonResponse(
            {"error": gettext("سقف اسکن این نشست پر شده است.")}, status=429
        )
    code = ""
    if request.content_type and "json" in request.content_type:
        try:
            code = str(json.loads(request.body or b"{}").get("code", ""))
        except (ValueError, AttributeError):
            code = ""
    if not code:
        code = request.POST.get("code", "")
    product = resolve_scan_product(session.company, code)
    if product is None:
        return JsonResponse(
            {"error": gettext("کالایی با این کد یافت نشد.")}, status=404
        )
    ScanSubmission.objects.create(session=session, product=product, code=code.strip())
    return JsonResponse(
        {"ok": True, "product": {"name": product.name, "sku": product.sku}}
    )
