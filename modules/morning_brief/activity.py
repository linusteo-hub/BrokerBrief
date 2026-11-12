"""
modules/morning_brief/activity.py

Freight — physical activity, from IMF PortWatch: ship transits through key
chokepoints and port calls at key ports. This is activity, not freight
rates, and is labelled as such.

Each figure is a 7-day total ending on the layer's latest date, compared with
the 7 days before. PortWatch publishes in weekly batches ~8–10 days behind,
so we fetch 35 days to be sure of two full weeks. A location missing any day
in either window is excluded rather than compared on unequal weeks.

Locations are identified by PortWatch portid, not name: names are not
stable or unique (e.g. Houston is "Houston (US-TX)").
"""

from datetime import date, timedelta
from typing import Callable

from modules.morning_brief.allowlist import require_allowed
from modules.morning_brief.checks import check_range, check_staleness
from modules.morning_brief.figures import count, fmt_date, make_change, make_figure
from modules.morning_brief.guarded_http import guarded_get
from modules.portwatch import fetch_daily_rows
from modules.provenance import utc_date

SOURCE_ID = "imf_portwatch"
LOOKBACK_DAYS = 35
WINDOW = 7
WEEKLY_RANGE = (0, 10_000)   # plausible 7-day total for any single location

CHOKEPOINTS = {
    "chokepoint1": "Suez Canal",
    "chokepoint2": "Panama Canal",
    "chokepoint4": "Bab el-Mandeb Strait",
    "chokepoint5": "Strait of Malacca",
    "chokepoint6": "Strait of Hormuz",
    "chokepoint7": "Cape of Good Hope",
}
PORTS = {
    "port1201": "Singapore",
    "port1114": "Rotterdam",
    "port362": "Fujairah",
    "port955": "Port Hedland",
    "port481": "Houston",
}

LAYERS = (
    # (layer, locations, value field, noun, figure id prefix)
    ("chokepoints", CHOKEPOINTS, "n_total", "transits", "transits"),
    ("ports", PORTS, "portcalls", "port calls", "portcalls"),
)


def weekly_figures(rows: list, locations: dict, field: str, noun: str, prefix: str,
                   today: date) -> tuple[list, list]:
    """Rows for one layer -> (figures, excluded)."""
    source = require_allowed(SOURCE_ID, numeric=True)
    by_location: dict[str, dict[date, float]] = {pid: {} for pid in locations}
    for row in rows:
        # `date` is a "YYYY-MM-DD" string today; older layers sent epoch ms.
        # Always the UTC date (utc_date converts explicitly), so the machine's
        # time zone or an offset in the source can never move a day.
        day = utc_date(row.get("date"))
        try:
            pid, value = row["portid"], float(row[field])
        except (KeyError, TypeError, ValueError):
            continue
        if day is None:
            continue
        if pid in by_location:
            by_location[pid][day] = value

    all_days = [d for series in by_location.values() for d in series]
    if not all_days:
        return [], [{"id": f"{prefix}_{pid}", "code": "no_data", "reason": "PortWatch returned no usable rows"}
                    for pid in locations]

    latest = max(all_days)
    stale = check_staleness(latest, today, source.max_age)
    if stale:
        return [], [{"id": f"{prefix}_{pid}", "code": "stale", "reason": stale} for pid in locations]

    this_week = [latest - timedelta(days=i) for i in range(WINDOW)]
    last_week = [latest - timedelta(days=WINDOW + i) for i in range(WINDOW)]
    fmt = count(noun)
    figures, excluded = [], []
    for pid, name in locations.items():
        series = by_location[pid]
        figure_id = f"{prefix}_{pid}"
        missing = [d for d in this_week + last_week if d not in series]
        if missing:
            excluded.append({"id": figure_id, "code": "incomplete",
                             "reason": f"{name}: {len(missing)} of 14 days missing, so the weeks cannot be compared"})
            continue
        total = sum(series[d] for d in this_week)
        previous = sum(series[d] for d in last_week)
        problem = check_range(total, *WEEKLY_RANGE, fmt(total))
        if problem:
            excluded.append({"id": figure_id, "code": "out_of_range", "reason": f"{name}: {problem}"})
            continue
        change = make_change(total, previous, fmt, decimals=0, basis="previous 7 days",
                             compared_with=f"7 days to {fmt_date(last_week[0])}")
        figures.append(make_figure(
            figure_id=figure_id,
            label=f"{name} {noun}, 7 days to {fmt_date(latest)}",
            unit=noun, value=total, fmt=fmt, as_of=latest, source_id=SOURCE_ID,
            quality_tier=source.quality_tier, changes=[change],
            notes="Physical activity from AIS ship tracking, not freight rates."))
    return figures, excluded


def fetch_activity(today: date, get: Callable = guarded_get) -> dict:
    """Returns {"items": [...], "excluded": [...], "error": str|None}."""
    start = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    items, excluded, errors = [], [], []
    for layer, locations, field, noun, prefix in LAYERS:
        result = fetch_daily_rows(layer, list(locations), start, ["date", "portid", "portname", field], get=get)
        if not result["success"]:
            error = f"PortWatch {layer} request failed: {result['error']}"
            errors.append(error)
            excluded += [{"id": f"{prefix}_{pid}", "code": "feed_failed", "reason": error} for pid in locations]
            continue
        figures, dropped = weekly_figures(result["rows"], locations, field, noun, prefix, today)
        items += figures
        excluded += dropped
    return {"items": items, "excluded": excluded, "error": "; ".join(errors) or None}
