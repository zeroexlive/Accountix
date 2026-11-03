"""Sprint 30 — SVG charts + motion pins (ADR-056).

The chart helpers are pure geometry over the reporting layer's
derived data, so they are pinned numerically: invert any plotted
coordinate and the ``period_series`` value comes back; donut arcs
sum to the full circle exactly (to printed precision); empty and
degenerate inputs produce the honest ``None`` the template turns
into an empty state. The CSS pins are string-level, like the
Sprint 22/28 design pins: every keyframe animation and every
geometry-moving rule must live inside the
``prefers-reduced-motion: no-preference`` block.
"""

import math
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings

from apps.reporting import charts
from apps.reporting import services as dash
from apps.reporting.tests.test_dashboard_v2 import _post, _two_period_world
from apps.treasury.tests._helpers import D

pytestmark = pytest.mark.django_db

BASELINE = 198
TOP = 16


def _series():
    company, fy, p1, p2, cash, revenue, expense = _two_period_world()
    _post(
        company,
        p1.start_date.replace(day=15),
        [{"account": cash, "debit": D("1000")}, {"account": revenue, "credit": D("1000")}],
    )
    _post(
        company,
        p1.start_date.replace(day=16),
        [{"account": expense, "debit": D("250")}, {"account": cash, "credit": D("250")}],
    )
    _post(
        company,
        p2.start_date.replace(day=15),
        [{"account": cash, "debit": D("1500")}, {"account": revenue, "credit": D("1500")}],
    )
    _post(
        company,
        p2.start_date.replace(day=16),
        [{"account": expense, "debit": D("500")}, {"account": cash, "credit": D("500")}],
    )
    return dash.period_series(company, fy)


def _parse_points(points_str):
    return [tuple(float(v) for v in pair.split(",")) for pair in points_str.split()]


def _invert(y, peak):
    """Map a plotted y back to the value it represents."""
    return (BASELINE - y) / (BASELINE - TOP) * peak


def test_area_chart_plots_period_series_values_exactly():
    series = _series()
    chart = charts.area_chart(series)
    assert chart is not None
    assert chart["peak"] == D("1500")

    revenue_pts = _parse_points(chart["revenue_points"])
    expenses_pts = _parse_points(chart["expenses_points"])
    assert len(revenue_pts) == len(series) == 2
    # Endpoints: x runs from the left edge to the right edge.
    assert revenue_pts[0][0] == 8 and revenue_pts[-1][0] == 712
    # Inverting every plotted y returns the period_series value
    # (within the 0.1-unit output rounding of the coordinates).
    for i, row in enumerate(series):
        assert _invert(revenue_pts[i][1], 1500) == pytest.approx(float(row["revenue"]), abs=9)
        assert _invert(expenses_pts[i][1], 1500) == pytest.approx(float(row["expenses"]), abs=9)
    # The maximum value touches the top of the plot exactly.
    assert revenue_pts[1][1] == TOP
    # Dots carry the raw values for the tooltips.
    assert [d["revenue"] for d in chart["dots"]] == [D("1000"), D("1500")]
    assert [d["label"] for d in chart["dots"]] == ["P1", "P2"]
    # The area path closes along the baseline.
    assert chart["revenue_area"].startswith("M ")
    assert f",{BASELINE} Z" in chart["revenue_area"]


def test_area_chart_single_period_is_a_sane_degenerate():
    series = _series()[:1]
    chart = charts.area_chart(series)
    assert chart is not None
    pts = _parse_points(chart["revenue_points"])
    assert len(pts) == 1
    assert pts[0][0] == 360  # centred
    assert pts[0][1] == TOP  # the single value is the peak
    assert chart["revenue_area"].endswith("Z")


def test_area_chart_empty_and_all_zero_are_honest_none():
    assert charts.area_chart([]) is None
    zero_series = [{"label": "P1", "revenue": D("0"), "expenses": D("0")}]
    assert charts.area_chart(zero_series) is None


def test_donut_segments_sum_to_the_full_circle():
    parts = [
        {"key": "a", "value": D("1")},
        {"key": "b", "value": D("1")},
        {"key": "c", "value": D("1")},
    ]
    segments = charts.donut_segments(parts)
    circumference = round(2 * math.pi * charts.RING_RADIUS, 2)
    assert sum(s["dash"] for s in segments) == pytest.approx(circumference, abs=0.011)
    # Offsets chain: each segment starts where the previous ended.
    assert segments[0]["offset"] == 0
    assert segments[1]["offset"] == -segments[0]["dash"]
    assert segments[2]["offset"] == -(segments[0]["dash"] + segments[1]["dash"])
    assert [s["share"] for s in segments] == [Decimal("33.3")] * 3


def test_donut_zero_total_is_none():
    assert charts.donut_segments([{"key": "a", "value": D("0")}]) is None


def test_percent_ring_matches_the_performance_share():
    assert charts.percent_ring(None) is None
    ring = charts.percent_ring(Decimal("45.5"))
    circumference = round(2 * math.pi * charts.RING_RADIUS, 2)
    assert ring["dash"] == pytest.approx(0.455 * circumference, abs=0.02)
    assert ring["share"] == Decimal("45.5")
    empty = charts.percent_ring(Decimal("0"))
    assert empty["dash"] == 0
    full = charts.percent_ring(Decimal("100"))
    assert full["dash"] == pytest.approx(circumference, abs=0.011)


def test_dashboard_data_carries_chart_and_rings():
    from apps.reporting.tests.test_reporting import _seed_with_cash_receipt

    w, purchase, sale = _seed_with_cash_receipt()
    data = dash.dashboard_data(w.company)
    assert data["chart"] is not None
    assert data["chart"]["peak"] == data["series_revenue_total"]
    rings = {row["key"]: row["ring"] for row in data["performance"]}
    assert rings["collections"] is not None
    assert rings["collections"]["share"] == Decimal("45.5")
    assert rings["cheques"] is None  # zero denominator -> empty state


# ---------------------------------------------------------------------------
# Motion: everything that moves lives in the reduced-motion block.
# ---------------------------------------------------------------------------


def _css():
    path = Path(settings.BASE_DIR) / "static" / "css" / "app.css"
    return path.read_text(encoding="utf-8")


def _motion_block(css):
    marker = "@media (prefers-reduced-motion: no-preference)"
    start = css.index(marker)
    # The block is the last construct in the sheet.
    return css[start:]


def test_all_keyframes_and_animations_are_reduced_motion_gated():
    css = _css()
    block = _motion_block(css)
    outside = css[: css.index("@media (prefers-reduced-motion: no-preference)")]
    assert "@keyframes" not in outside
    assert "animation:" not in outside
    for name in ("tile-in", "draw-line", "fade-in", "ring-in"):
        assert f"@keyframes {name}" in block
    # The chart draw-in + tile entrance + ring grow are the block's
    # payload, at the ADR's 150-250ms durations.
    assert "animation:draw-line .25s" in block
    assert "animation:tile-in .22s" in block
    assert "animation:ring-in .22s" in block


def test_no_transform_transitions_outside_the_motion_block():
    css = _css()
    outside = css[: css.index("@media (prefers-reduced-motion: no-preference)")]
    # Movement-bearing transitions (transform) are gated; color-only
    # transitions elsewhere animate no geometry (ADR-056).
    assert not re.search(r"transition:[^;}]*transform", outside)
    block = _motion_block(css)
    assert "transition:transform .18s ease" in block
    assert "translateY(-2px)" in block


def test_removed_css_charts_leave_no_dead_rules():
    css = _css()
    assert ".bar-chart" not in css
    assert ".progress" not in css
    assert ".chart-svg .line.rev" in css
    assert ".ring-val" in css
