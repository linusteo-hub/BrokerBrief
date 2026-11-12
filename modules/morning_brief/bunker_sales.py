"""
modules/morning_brief/bunker_sales.py

Singapore bunker sales by fuel type, from the Maritime and Port Authority of
Singapore (MPA) dataset "Bunker Sales Breakdown, Monthly" on data.gov.sg.

Why this source: it is the port authority's own count of what was actually
delivered in the world's largest bunkering port, published under the
Singapore Open Data Licence, which allows copying and redistribution with
attribution. It is a volume series, not a price: BrokerBrief still has no
publishable bunker price.

How it behaves:
- One row per month per fuel type. MPA publishes a month's figures around the
  third week of the following month (September 2026 appeared on 21-10-2026),
  and marks the latest month as a preliminary estimate.
- Values are in thousand tonnes. (The dataset's own description says
  "tonnes"; the values, e.g. 4,726.39 for a month, are thousands of tonnes.)
  The range check below would refuse a month published in plain tonnes, so a
  silent unit change cannot reach the brief.
- One small request per run: the newest 14 months x 16 fuel types.

A month is used only if every fuel type listed in FUEL_TYPES has a row for
it, in the latest month and in each month it is compared with; otherwise the
figure is excluded with the reason, never compared on unequal data.
"""

import calendar
from datetime import date, timedelta
from typing import Callable, Optional

from modules.morning_brief.allowlist import SourceNotAllowed, require_allowed
from modules.morning_brief.checks import check_range, check_staleness
from modules.morning_brief.figures import make_change, make_figure
from modules.morning_brief.guarded_http import guarded_get

SOURCE_ID = "mpa_bunker_sales"
API_URL = "https://data.gov.sg/api/action/datastore_search"
RESOURCE_ID = "d_4f5abbf4486bf8e52bbed3be56dde562"   # Bunker Sales Breakdown, Monthly
ROW_LIMIT = 224                                      # 14 months x 16 fuel types

# The 16 fuel types in the dataset (recorded 12-11-2026). A month missing any
# of them is treated as incomplete.
FUEL_TYPES = (
    "Marine Diesel Oil", "Bio-Blended Marine Diesel Oil",
    "Marine Gas Oil", "Bio-Blended Marine Gas Oil",
    "Low Sulphur Marine Gas Oil", "Bio-Blended Low Sulphur Marine Gas Oil",
    "Marine Fuel Oil", "Bio-Blended Marine Fuel Oil",
    "Low Sulphur Fuel Oil", "Bio-Blended Low Sulphur Fuel Oil",
    "Ultra Low Sulphur Fuel Oil", "Bio-Blended Ultra Low Sulphur Fuel Oil",
    "B100", "LNG", "Methanol", "Ammonia",
)

# Figures published in the brief: (id, label, fuel types summed). A label that
# sums several of MPA's types says so, because it is then our calculation.
FIGURES = (
    ("sg_bunker_total", "Singapore bunker sales, all fuel types (BrokerBrief sum of MPA's types)", FUEL_TYPES),
    ("sg_bunker_lsfo", "Low sulphur fuel oil (MPA type: Low Sulphur Fuel Oil)", ("Low Sulphur Fuel Oil",)),
    ("sg_bunker_mfo", "Marine fuel oil, the high-sulphur grades (MPA type: Marine Fuel Oil)", ("Marine Fuel Oil",)),
    ("sg_bunker_lsmgo", "Low sulphur marine gas oil (MPA type: Low Sulphur Marine Gas Oil)",
     ("Low Sulphur Marine Gas Oil",)),
    ("sg_bunker_bio", "Biofuel blends and B100 (BrokerBrief sum of MPA's bio-blended types and B100)",
     tuple(t for t in FUEL_TYPES if t.startswith("Bio-Blended")) + ("B100",)),
    ("sg_bunker_lng", "LNG (MPA type: LNG)", ("LNG",)),
)

UNIT = "thousand tonnes"
DECIMALS = 2                    # as MPA publishes it
# Plausible monthly ranges in thousand tonnes. Monthly totals since 2015 have
# been roughly 3,300 to 5,500; a total outside 1,000–10,000 means a unit or
# data error. Components are only bounded above.
TOTAL_RANGE = (1_000.0, 10_000.0)
COMPONENT_RANGE = (0.0, 10_000.0)


def fmt(value: float) -> str:
    return f"{value:,.{DECIMALS}f} {UNIT}"


def month_end(month: str) -> date:
    """'2026-09' -> date(2026, 9, 30)."""
    year, mon = (int(part) for part in month.split("-"))
    return date(year, mon, calendar.monthrange(year, mon)[1])


def month_display(month: str) -> str:
    """'2026-09' -> 'September 2026'."""
    return month_end(month).strftime("%B %Y")


def shift_month(month: str, by: int) -> str:
    year, mon = (int(part) for part in month.split("-"))
    index = year * 12 + (mon - 1) + by
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def parse_records(records: list) -> dict:
    """Rows -> {month: {fuel_type: thousand tonnes}}. A row with a missing or
    non-numeric value is skipped, which leaves its month incomplete."""
    months: dict[str, dict[str, float]] = {}
    for row in records:
        try:
            month, fuel_type, value = str(row["month"]), str(row["bunker_type"]), float(row["bunker_sales"])
            month_end(month)
        except (KeyError, TypeError, ValueError):
            continue
        months.setdefault(month, {})[fuel_type] = value
    return months


def is_complete(by_type: Optional[dict]) -> bool:
    return by_type is not None and all(t in by_type for t in FUEL_TYPES)


def build_figures(months: dict, today: date) -> tuple[list, list]:
    """Return (figures, excluded). Every figure in FIGURES ends up in one of them."""
    source = require_allowed(SOURCE_ID, numeric=True)
    ids = [figure_id for figure_id, _, _ in FIGURES]

    def exclude_all(code: str, reason: str):
        return [], [{"id": figure_id, "code": code, "reason": reason} for figure_id in ids]

    if not months:
        return exclude_all("no_data", "MPA returned no usable rows")
    latest = max(months)
    if not is_complete(months[latest]):
        missing = [t for t in FUEL_TYPES if t not in months[latest]]
        return exclude_all("incomplete", f"MPA's figures for {month_display(latest)} lack "
                                         f"{len(missing)} of {len(FUEL_TYPES)} fuel types ({', '.join(missing)})")
    stale = check_staleness(month_end(latest), today, source.max_age)
    if stale:
        return exclude_all("stale", stale)

    comparisons = (("previous month", shift_month(latest, -1)),
                   ("same month a year earlier", shift_month(latest, -12)))
    figures, excluded = [], []
    for figure_id, label, types in FIGURES:
        value = round(sum(months[latest][t] for t in types), DECIMALS)
        low, high = TOTAL_RANGE if figure_id == "sg_bunker_total" else COMPONENT_RANGE
        problem = check_range(value, low, high, fmt(value))
        if problem:
            excluded.append({"id": figure_id, "code": "out_of_range", "reason": problem})
            continue
        changes = []
        for basis, other in comparisons:
            if is_complete(months.get(other)):
                previous = round(sum(months[other][t] for t in types), DECIMALS)
                changes.append(make_change(value, previous, fmt, decimals=DECIMALS,
                                           basis=basis, compared_with=month_display(other)))
        figure = make_figure(
            figure_id=figure_id, label=label, unit=UNIT, value=value, fmt=fmt,
            as_of=month_end(latest), source_id=SOURCE_ID, quality_tier=source.quality_tier,
            changes=changes,
            notes="Monthly total. MPA marks the latest month's figures as preliminary estimates.",
            plausible_range=(low, high))
        figure["as_of_display"] = month_display(latest)     # a month, not a day
        figure["period"] = "month"
        figures.append(figure)

    # If the total failed its range check the components cannot be trusted either.
    if any(e["id"] == "sg_bunker_total" for e in excluded):
        reason = next(e["reason"] for e in excluded if e["id"] == "sg_bunker_total")
        return exclude_all("out_of_range", reason)
    return figures, excluded


def fetch_bunker_sales(today: date, get: Callable = guarded_get) -> dict:
    """Fetch and check MPA's monthly bunker sales.

    Returns {"items": [...], "excluded": [{"id", "code", "reason"}], "error": str|None},
    the same shape as fetch_prices(). Never raises for a feed problem: a
    failure becomes `error` and every figure is listed as excluded.
    """
    def failed(error: str) -> dict:
        return {"items": [], "error": error,
                "excluded": [{"id": figure_id, "code": "feed_failed", "reason": error}
                             for figure_id, _, _ in FIGURES]}

    try:
        response = get(API_URL, params={"resource_id": RESOURCE_ID, "limit": ROW_LIMIT, "sort": "month desc"},
                       timeout=20)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not body.get("success"):
            return failed("data.gov.sg reported an error for the MPA bunker sales dataset")
        records = body["result"]["records"]
        if not isinstance(records, list):
            raise ValueError("records is not a list")
    except SourceNotAllowed:
        raise                      # an allowlist refusal must fail loudly, never look like a feed outage
    except (KeyError, TypeError, ValueError) as error:
        return failed(f"MPA bunker sales response was not in the expected format ({type(error).__name__})")
    except Exception as error:     # network, HTTP status, timeout
        return failed(f"MPA bunker sales request failed: {type(error).__name__}")

    figures, excluded = build_figures(parse_records(records), today)
    return {"items": figures, "excluded": excluded, "error": None}
