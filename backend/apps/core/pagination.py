"""Shared list pagination + filter helpers for the server-rendered UI.

Every list view in Accountix is membership-filtered *before* it reaches
``paginate``; this module only slices the already-scoped queryset/list
and preserves the active filter parameters across page links.
"""

from django.core.paginator import Paginator

PAGE_SIZE = 25


def paginate(request, items, per_page=PAGE_SIZE):
    """Return ``(page_obj, filter_query)`` for a queryset or list.

    ``filter_query`` is the current GET query string without ``page``,
    ready to append to pagination links in templates.
    """
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page_obj, params.urlencode()


def apply_date_range(qs, params, field):
    """Apply optional ``date_from`` / ``date_to`` GET filters (inclusive)."""
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    if date_from:
        qs = qs.filter(**{f"{field}__gte": date_from})
    if date_to:
        qs = qs.filter(**{f"{field}__lte": date_to})
    return qs
