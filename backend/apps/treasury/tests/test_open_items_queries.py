"""Query-count regression test for open_items (Sprint 10 perf fix).

open_items originally ran two allocation aggregates per invoice, so
the dashboard's query count grew linearly with the number of open
invoices (116 queries at 50 invoices). The grouped implementation
must stay constant as the invoice count grows, with identical results.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.treasury import reporting
from apps.treasury.tests._helpers import build_world, post_purchase, post_sale

pytestmark = pytest.mark.django_db


def test_open_items_query_count_is_constant():
    w = build_world()
    post_purchase(w)
    sale1 = post_sale(w, number="SINV-Q1")
    items_small = reporting.open_items(w.company)
    with CaptureQueriesContext(connection) as ctx_small:
        reporting.open_items(w.company)
    # More invoices (different numbers) — the count must not grow.
    # A second purchase first, so total stock covers four sales of 4.
    post_purchase(w, number="PINV-Q2")
    post_sale(w, number="SINV-Q2")
    post_sale(w, number="SINV-Q3")
    post_sale(w, number="SINV-Q4")
    with CaptureQueriesContext(connection) as ctx_large:
        items_large = reporting.open_items(w.company)
    assert len(items_large) > len(items_small)
    assert len(ctx_large) == len(ctx_small), (
        f"open_items queries grew from {len(ctx_small)} to {len(ctx_large)} "
        "when invoices were added — per-invoice aggregates are back"
    )
    # Results are still correct: the first sale is fully open (1100 with tax).
    first = [i for i in items_large if i["invoice"].id == sale1.id]
    assert len(first) == 1
    assert first[0]["outstanding"] == first[0]["total"]
