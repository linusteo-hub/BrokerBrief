"""
modules/morning_brief/port_traffic.py

Singapore port activity from the Maritime and Port Authority of Singapore
(MPA), on data.gov.sg: "Vessel Arrivals (>75 GT) Total, Monthly" and
"Vessel Calls (>75 GT), Monthly" (calls by purpose).

Why this source: IMF PortWatch's daily port and chokepoint data began to
require a token in November 2026. MPA's monthly counts are the port
authority's own, published under the Singapore Open Data Licence (copy and
redistribute with attribution), the same terms as the bunker sales the brief
already uses. They are counts of vessels over 75 GT, not freight rates, and
cover Singapore only.

What is shown and what is not:
- Total vessel arrivals (MPA's own total).
- Calls for bunkers and calls for cargo, as MPA counts them by purpose. MPA
  does not say whether one call can be counted under more than one purpose, so
  BrokerBrief never adds the purposes into a total.
- Gross tonnage is not used.
- MPA marks the latest month as a preliminary estimate; every figure says so.

Two small requests per run (14 months of arrivals; up to 200 rows of calls, of
which 14 months x 5 purposes are used today). A missing comparison month or an
unreadable row is stated in the figure's notes, never dropped silently.
"""

from datetime import date
from typing import Callable

from modules.morning_brief.allowlist import SourceNotAllowed, require_allowed
from modules.morning_brief.bunker_sales import month_display, month_end, shift_month
from modules.morning_brief.checks import check_range, check_staleness
from modules.morning_brief.figures import count, make_change, make_figure, make_series
from modules.morning_brief.guarded_http import guarded_get

SOURCE_ID = "mpa_port_traffic"
API_URL = "https://data.gov.sg/api/action/datastore_search"
ARRIVALS_RESOURCE = "d_d48c5a038904f6da3c603cd854b6c191"    # Vessel Arrivals (>75 GT) Total, Monthly
CALLS_RESOURCE = "d_48cb38d12697d3463c8cadfb22e6c61d"       # Vessel Calls (>75 GT), Monthly
PURPOSES = ("Cargo", "Repairs", "Bunkers", "Supplies", "Others")
MONTHS = 14
CALLS_ROW_LIMIT = 200       # 14 months x 5 purposes is 70; asked generously so a new purpose cannot cut months off
CHART_MONTHS = 13
DATASET_URLS = {
    "arrivals": "https://data.gov.sg/datasets/d_d48c5a038904f6da3c603cd854b6c191/view",
    "calls": "https://data.gov.sg/datasets/d_48cb38d12697d3463c8cadfb22e6c61d/view",
}
NOTE = "Vessels over 75 GT, Singapore only. MPA marks the latest month's figures as preliminary estimates."

# (id, label, short label, dataset key, noun, plausible monthly range)
# Ranges are wide on purpose: monthly arrivals have run at roughly 10,000-12,500 and
# bunker calls at roughly 3,000-4,000 in recent years; a value outside is refused.
FIGURES = (
    ("sg_vessel_arrivals", "Vessel arrivals at Singapore, all types (MPA: Vessel Arrivals (>75 GT) Total)",
     "Vessel arrivals", "arrivals", "arrivals", (3_000, 30_000)),
    ("sg_calls_bunkers", "Vessel calls for bunkers (MPA purpose type: Bunkers)",
     "Calls for bunkers", "Bunkers", "calls", (500, 15_000)),
    ("sg_calls_cargo", "Vessel calls for cargo (MPA purpose type: Cargo)",
     "Calls for cargo", "Cargo", "calls", (500, 15_000)),
)


def parse_arrivals(records: list) -> tuple:
    """Rows -> ({month: count}, rows skipped). A row with a missing or non-numeric value is
    skipped and counted, so the figure can say so."""
    out, skipped = {}, 0
    for row in records:
        try:
            month, value = str(row["month"]), int(row["number_of_vessels"])
            month_end(month)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        out[month] = value
    return out, skipped


def parse_calls(records: list) -> tuple:
    """Rows -> ({purpose: {month: count}}, rows skipped)."""
    out: dict[str, dict[str, int]] = {}
    skipped = 0
    for row in records:
        try:
            month, purpose, value = str(row["month"]), str(row["purpose_type"]), int(row["number_of_vessel_calls"])
            month_end(month)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        out.setdefault(purpose, {})[month] = value
    return out, skipped


def build_figure(figure_id: str, label: str, short: str, noun: str, low_high: tuple,
                 by_month: dict, today: date, *, skipped: int = 0, dataset_url: str = "") -> tuple:
    """Return (figure, None) or (None, {"code", "reason"})."""
    source = require_allowed(SOURCE_ID, numeric=True)
    if not by_month:
        return None, {"code": "no_data", "reason": "MPA returned no usable rows"}
    fmt = count(noun)
    latest = max(by_month)
    value = by_month[latest]
    stale = check_staleness(month_end(latest), today, source.max_age)
    if stale:
        return None, {"code": "stale", "reason": stale}
    problem = check_range(value, low_high[0], low_high[1], fmt(value))
    if problem:
        return None, {"code": "out_of_range", "reason": problem}
    changes, gaps = [], []
    for basis, other in (("previous month", shift_month(latest, -1)),
                         ("same month a year earlier", shift_month(latest, -12))):
        if other in by_month:
            changes.append(make_change(value, by_month[other], fmt, decimals=0,
                                       basis=basis, compared_with=month_display(other)))
        else:                                   # say why a comparison is absent, never drop it silently
            gaps.append(f"No {basis} comparison: MPA returned no figure for {month_display(other)}.")
    notes = " ".join([NOTE] + gaps + ([f"{skipped} unreadable MPA row{'s' if skipped != 1 else ''} skipped."]
                                       if skipped else []))
    history = []
    for back in range(CHART_MONTHS):          # stops at the first missing month: no silent gap
        month = shift_month(latest, -back)
        if month not in by_month:
            break
        history.append((month_end(month), by_month[month]))
    chart, chart_note = make_series(history[::-1], fmt, label="Monthly count as published by MPA",
                                    date_display=lambda d: d.strftime("%B %Y"), plausible_range=low_high)
    figure = make_figure(figure_id=figure_id, label=label, unit=noun, value=value, fmt=fmt,
                         as_of=month_end(latest), source_id=SOURCE_ID, quality_tier=source.quality_tier,
                         changes=changes, notes=notes, plausible_range=low_high,
                         series=chart, series_note=chart_note)
    figure["as_of_display"] = month_display(latest)
    figure["period"] = "month"
    figure["short_label"] = short
    figure["preliminary"] = True          # MPA marks the latest month as a preliminary estimate
    if dataset_url:
        figure["dataset_url"] = dataset_url
    return figure, None


def fetch_port_traffic(today: date, get: Callable = guarded_get) -> dict:
    """Fetch and check MPA's monthly arrivals and calls.

    Returns {"items": [...], "excluded": [{"id", "code", "reason"}], "error": str|None},
    the same shape as the other fetchers. Never raises for a feed problem.
    """
    def request(resource: str, limit: int) -> list:
        response = get(API_URL, params={"resource_id": resource, "limit": limit, "sort": "month desc"}, timeout=20,
                       source_id=SOURCE_ID)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not body.get("success"):
            raise ValueError("data.gov.sg reported an error")
        records = body["result"]["records"]
        if not isinstance(records, list):
            raise ValueError("records is not a list")
        return records

    def failed(error: str) -> dict:
        return {"items": [], "error": error,
                "excluded": [{"id": f[0], "code": "feed_failed", "reason": error} for f in FIGURES]}

    try:
        arrivals, arrivals_skipped = parse_arrivals(request(ARRIVALS_RESOURCE, MONTHS))
        calls, calls_skipped = parse_calls(request(CALLS_RESOURCE, CALLS_ROW_LIMIT))
    except SourceNotAllowed:
        raise
    except (KeyError, TypeError, ValueError) as error:
        return failed(f"MPA vessel arrivals/calls response was not in the expected format ({type(error).__name__}: "
                      f"{str(error)[:120]})")
    except Exception as error:      # network, HTTP status, timeout; data.gov.sg needs no key
        return failed(f"MPA vessel arrivals/calls request failed: {type(error).__name__}: {str(error)[:200]}")

    items, excluded = [], []
    for figure_id, label, short, key, noun, low_high in FIGURES:
        dataset = "arrivals" if key == "arrivals" else "calls"
        by_month = arrivals if dataset == "arrivals" else calls.get(key, {})
        figure, problem = build_figure(figure_id, label, short, noun, low_high, by_month, today,
                                       skipped=arrivals_skipped if dataset == "arrivals" else calls_skipped,
                                       dataset_url=DATASET_URLS[dataset])
        if figure:
            items.append(figure)
        else:
            excluded.append({"id": figure_id, **problem})
    return {"items": items, "excluded": excluded, "error": None}
