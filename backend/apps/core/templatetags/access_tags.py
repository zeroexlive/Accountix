"""Role lookup tags for templates (Sprint 25, ADR-050).

``{% company_role object.company as role %}`` exposes the current
user's role in the page object's company so detail templates can hide
action buttons the role cannot use. Presentation only — the views
enforce the same tiers server-side regardless of what renders.
"""

from django import template

from apps.core.access import ADMINISTER_ROLES, GOVERN_ROLES, OPERATE_ROLES, role_for

register = template.Library()

_TIERS = {
    "OPERATE": OPERATE_ROLES,
    "ADMINISTER": ADMINISTER_ROLES,
    "GOVERN": GOVERN_ROLES,
}


@register.simple_tag(takes_context=True)
def company_role(context, company):
    user = context.get("user")
    if user is None or company is None:
        return ""
    return role_for(user, company) or ""


@register.simple_tag(takes_context=True)
def company_can(context, company, tier):
    """True when the current user's role in ``company`` reaches ``tier``
    ("OPERATE" / "ADMINISTER" / "GOVERN") — the boolean form templates
    use to hide action blocks."""
    user = context.get("user")
    if user is None or company is None:
        return False
    role = role_for(user, company)
    return role is not None and role in _TIERS.get(tier, ())
