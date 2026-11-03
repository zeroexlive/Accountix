"""Server-rendered SVG chart geometry (Sprint 30, ADR-056).

Pure functions over the reporting layer's derived data — the same
``period_series`` rows and ``_performance`` percentages the dashboard
already pins numerically. Geometry is computed here, in Python, so
the template stays arithmetic-free (the ADR-031 convention) and the
plotted coordinates can be pinned by tests against the source
values: invert any plotted y and you get the period_series value
back (within the 0.1-unit output rounding).

Honesty rules mirror the rest of the dashboard: nothing to plot
(no rows, or a zero peak / zero total) returns ``None`` and the
template renders the existing empty state — a chart is never
fabricated from zeros. The time axis runs left-to-right in both
locales (chart convention, like the numerals themselves); the
template wraps the SVG in ``dir="ltr"``.
"""

import math
from decimal import Decimal

ZERO = Decimal("0")

# Area-chart canvas. The plot area leaves room on the left for the
# peak label and below for the period labels.
AREA_WIDTH = 720
AREA_HEIGHT = 232
_AREA_LEFT = 8
_AREA_RIGHT = 712
_AREA_TOP = 16
_AREA_BASELINE = 198


def _num(value):
    """Round a coordinate for output: one decimal, ints stay ints."""
    rounded = round(float(value), 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _points_str(points):
    return " ".join(f"{_num(x)},{_num(y)}" for x, y in points)


def _area_path(points, baseline):
    if len(points) == 1:
        x, y = points[0]
        # A single period has no width to fill; draw a thin sliver
        # around the point so the area stays visible and honest.
        return (
            f"M {_num(x - 14)},{_num(baseline)} L {_num(x - 14)},{_num(y)} "
            f"L {_num(x + 14)},{_num(y)} L {_num(x + 14)},{_num(baseline)} Z"
        )
    head = " ".join(
        (f"M {_num(points[0][0])},{_num(points[0][1])}")
        if i == 0
        else f"L {_num(x)},{_num(y)}"
        for i, (x, y) in enumerate(points)
    )
    return (
        f"{head} L {_num(points[-1][0])},{_num(baseline)} "
        f"L {_num(points[0][0])},{_num(baseline)} Z"
    )


def area_chart(series):
    """Revenue-vs-expenses area/line geometry for ``period_series``.

    Returns ``None`` when there are no rows or every value is zero
    (honest empty state). Otherwise a dict with polyline point
    strings, area path data, per-point dots (coordinates + the raw
    values, for <title> tooltips) and x labels — all derived from
    the rows' ``revenue``/``expenses`` Decimals and nothing else.
    """
    rows = list(series)
    if not rows:
        return None
    peak = max([row["revenue"] for row in rows] + [row["expenses"] for row in rows] + [ZERO])
    if peak <= ZERO:
        return None

    plot_w = _AREA_RIGHT - _AREA_LEFT
    plot_h = _AREA_BASELINE - _AREA_TOP
    n = len(rows)
    if n == 1:
        xs = [(_AREA_LEFT + _AREA_RIGHT) / 2]
    else:
        xs = [_AREA_LEFT + i * plot_w / (n - 1) for i in range(n)]

    def y_of(value):
        return _AREA_BASELINE - float(value / peak) * plot_h

    revenue_points = [(xs[i], y_of(row["revenue"])) for i, row in enumerate(rows)]
    expenses_points = [(xs[i], y_of(row["expenses"])) for i, row in enumerate(rows)]
    return {
        "width": AREA_WIDTH,
        "height": AREA_HEIGHT,
        "baseline": _AREA_BASELINE,
        "peak": peak,
        "peak_label": str(peak),
        "revenue_points": _points_str(revenue_points),
        "expenses_points": _points_str(expenses_points),
        "revenue_area": _area_path(revenue_points, _AREA_BASELINE),
        "expenses_area": _area_path(expenses_points, _AREA_BASELINE),
        "dots": [
            {
                "x": _num(xs[i]),
                "revenue_y": _num(revenue_points[i][1]),
                "expenses_y": _num(expenses_points[i][1]),
                "label": row["label"],
                "revenue": row["revenue"],
                "expenses": row["expenses"],
            }
            for i, row in enumerate(rows)
        ],
        "labels": [
            {"x": _num(xs[i]), "y": _AREA_BASELINE + 22, "text": row["label"]}
            for i, row in enumerate(rows)
        ],
    }


# Donut/ring geometry: segments are SVG circles sharing one radius,
# each showing its arc via stroke-dasharray, rotated -90 degrees so
# the first segment starts at the top.
RING_RADIUS = 30
RING_CIRCUMFERENCE = 2 * math.pi * RING_RADIUS


def donut_segments(parts):
    """Arc geometry for parts of a whole.

    ``parts`` is a list of dicts with a Decimal ``value`` (>= 0).
    Returns ``None`` when the total is zero (the caller's honest
    empty state applies). Otherwise the parts, each annotated with
    ``share`` (percent, 1 decimal — the same convention as
    ``_performance``), ``dash`` (the visible arc length) and
    ``offset`` (dash offset positioning the segment after the
    previous ones). Segment lengths are rounded cumulatively, so
    they always sum to the full circumference exactly (to the
    printed precision) — the circle never gaps or overlaps.
    """
    values = [part["value"] for part in parts]
    total = sum(values, ZERO)
    if total <= ZERO:
        return None
    circumference = RING_CIRCUMFERENCE
    segments = []
    cumulative = ZERO
    previous_boundary = 0.0
    for part, value in zip(parts, values, strict=True):
        cumulative += value
        boundary = round(float(cumulative / total) * circumference, 2)
        segments.append(
            {
                **part,
                "share": (value * Decimal("100") / total).quantize(Decimal("0.1")),
                "dash": round(boundary - previous_boundary, 2),
                "offset": round(-previous_boundary, 2),
                "circumference": round(circumference, 2),
            }
        )
        previous_boundary = boundary
    return segments


def percent_ring(percent):
    """The two-segment ring for one ``_performance`` percentage:
    achieved share vs the remainder. ``percent`` is a Decimal in
    [0, 100] or ``None`` (zero denominator upstream) — ``None`` in,
    ``None`` out, so the template keeps its existing empty state."""
    if percent is None:
        return None
    segments = donut_segments(
        [
            {"key": "value", "value": percent},
            {"key": "rest", "value": Decimal("100") - percent},
        ]
    )
    if segments is None:  # percent == 0 and rest == 0 cannot happen; defensive
        return None
    return segments[0]
