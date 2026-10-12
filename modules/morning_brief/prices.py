"""
modules/morning_brief/prices.py

Section 1 (Prices): EIA Brent spot and New York Harbor ultra-low-sulphur
diesel spot. EIA publishes these daily values once a week, so the newest
value is often several days old; every figure carries its as-of date.

Units are kept as EIA publishes them (USD per barrel, USD per US gallon):
converting would make our figure differ from the source's.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from modules.eia import fetch_spot_series
from modules.morning_brief.allowlist import require_allowed
from modules.morning_brief.checks import check_range, check_staleness
from modules.morning_brief.figures import fmt_date, make_change, make_figure, money
from modules.morning_brief.guarded_http import guarded_get

SOURCE_ID = "eia_spot"
LOOKBACK_DAYS = 45          # enough rows for a week-on-week change after a long lag
WEEK_GAP_TOLERANCE = 5      # week-ago value may be up to 7+5 days before as_of (holidays)


@dataclass(frozen=True)
class PriceSeries:
    key: str
    series_id: str          # EIA series ID, read from EIA's spot-price table
    label: str
    unit: str
    decimals: int           # as EIA publishes it
    low: float              # plausible range; outside it the value is refused
    high: float


SERIES = (
    PriceSeries("brent_spot", "RBRTE", "Brent crude oil spot price (FOB Europe)",
                "USD/bbl", 2, 10.0, 300.0),
    PriceSeries("ulsd_nyh", "EER_EPD2DXL0_PF4_Y35NY_DPG",
                "New York Harbor ultra-low-sulphur diesel spot price",
                "USD/gal", 3, 0.5, 10.0),
)


def parse_rows(rows: list) -> list[tuple[date, float]]:
    """EIA rows -> [(date, value)] oldest first. Rows with a blank or
    non-numeric value (EIA uses these for holidays) are skipped."""
    observations = []
    for row in rows:
        try:
            observations.append((date.fromisoformat(row["period"]), float(row["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(observations)


def build_price_figure(series: PriceSeries, rows: list, today: date) -> tuple[Optional[dict], Optional[str]]:
    """Return (figure, None) or (None, reason it was excluded)."""
    source = require_allowed(SOURCE_ID, numeric=True)
    observations = parse_rows(rows)
    if not observations:
        return None, "EIA returned no usable values"

    as_of, value = observations[-1]
    fmt = money(series.unit, series.decimals)
    problem = (check_staleness(as_of, today, source.max_age)
               or check_range(value, series.low, series.high, fmt(value)))
    if problem:
        return None, problem

    changes = []
    if len(observations) >= 2:
        prev_date, prev_value = observations[-2]
        changes.append(make_change(value, prev_value, fmt, decimals=series.decimals,
                                   basis="previous published day",
                                   compared_with=fmt_date(prev_date)))
    week_target = as_of - timedelta(days=7)
    week_ago = [(d, v) for d, v in observations if d <= week_target]
    if week_ago and week_ago[-1][0] >= week_target - timedelta(days=WEEK_GAP_TOLERANCE):
        wk_date, wk_value = week_ago[-1]
        changes.append(make_change(value, wk_value, fmt, decimals=series.decimals,
                                   basis="one week earlier",
                                   compared_with=fmt_date(wk_date)))

    return make_figure(figure_id=series.key, label=series.label, unit=series.unit,
                       value=value, fmt=fmt, as_of=as_of, source_id=SOURCE_ID,
                       quality_tier=source.quality_tier, changes=changes), None


def fetch_prices(api_key: Optional[str], today: date, get: Callable = guarded_get) -> dict:
    """Fetch and check every price series.

    Returns {"items": [...], "excluded": [{"id", "reason"}], "error": str|None}.
    `get` is the HTTP getter: the allowlist-guarded one in production, a
    recorded-response stand-in in tests.
    """
    if not api_key:
        return {"items": [], "excluded": [], "error": "no EIA API key configured (set EIA_API_KEY)"}

    start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    items, excluded = [], []
    for series in SERIES:
        result = fetch_spot_series(api_key, series.series_id, start, get=get)
        if not result.get("success"):
            excluded.append({"id": series.key, "reason": f"EIA request failed: {result.get('error')}"})
            continue
        figure, problem = build_price_figure(series, result["rows"], today)
        if figure:
            items.append(figure)
        else:
            excluded.append({"id": series.key, "reason": problem})
    return {"items": items, "excluded": excluded, "error": None}
