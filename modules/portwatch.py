"""
modules/portwatch.py
Fetches port activity data from IMF Portwatch via ArcGIS FeatureServer.
No API key required.
"""

import requests
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict

from modules.provenance import PORTWATCH_MAX_AGE, QualityTier, SourceInfo, parse_as_of, stamp

PORTWATCH_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/"
    "ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query"
)

TARGET_PORTS = ["Singapore", "Rotterdam", "Fujairah", "Port Hedland", "Houston"]

PORTWATCH = SourceInfo(
    name="IMF Portwatch",
    url="https://portwatch.imf.org",
    licence="IMF Open Data Terms",
    quality_tier=QualityTier.LIVE_API,
    max_age=PORTWATCH_MAX_AGE,
)


def fetch_port_activity() -> dict:
    cutoff = (date.today() - timedelta(days=14)).strftime("%Y-%m-%d")
    port_list = ", ".join(f"'{p}'" for p in TARGET_PORTS)
    params = {
        "where":             f"portname IN ({port_list}) AND date >= DATE '{cutoff}'",
        "outFields":         "portname,date,portcalls,portcalls_tanker,portcalls_dry_bulk",
        "orderByFields":     "portname,date DESC",
        "returnGeometry":    "false",
        "resultRecordCount": 200,
        "f":                 "json",
    }
    try:
        response = requests.get(PORTWATCH_URL, params=params, timeout=15)
        response.raise_for_status()
        features = response.json().get("features", [])
        if not features:
            return {"success": False, "error": "No features returned"}

        rows = [
            {
                "portname":           f["attributes"].get("portname"),
                "date":               f["attributes"].get("date"),
                "portcalls":          f["attributes"].get("portcalls"),
                "portcalls_tanker":   f["attributes"].get("portcalls_tanker"),
                "portcalls_dry_bulk": f["attributes"].get("portcalls_dry_bulk"),
            }
            for f in features
        ]
        signals, reasons = _compute_congestion(rows, TARGET_PORTS)
        parsed_dates = [d for d in (parse_as_of(r["date"]) for r in rows) if d is not None]
        latest_as_of = max(parsed_dates) if parsed_dates else None

        return {
            "success":            True,
            "ports":              rows,
            # Every target port gets a signal; "Unknown" ones carry a reason.
            "congestion_signals": signals,
            "congestion_reasons": reasons,
            "source_name":        "IMF Portwatch",
            "source_url":         "https://portwatch.imf.org",
            "updated_at":         date.today().isoformat(),
            "confidence":         0.80,
            # Rows are ordered `portname, date DESC` (grouped per port, not globally
            # sorted) — as_of must be an explicit max() over all rows, not rows[0].
            "provenance":         stamp(PORTWATCH, as_of=latest_as_of),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _compute_congestion(rows: list, ports: list) -> tuple[dict, dict]:
    """-> (signals, reasons). Each port in `ports` gets "Rising", "Easing",
    "Stable" or "Unknown". Unknown is used when there is nothing to compare —
    no rows, fewer than 2 days, or zero calls on the earliest day — and every
    Unknown has a reason in `reasons`. Missing data must never read as Stable."""
    by_port = defaultdict(list)
    for row in rows:
        by_port[row["portname"]].append(row)

    signals, reasons = {}, {}
    for port in ports:
        # Sort on the parsed date: the layer has sent both ISO strings and epoch ms.
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        sorted_rows = sorted(
            [r for r in by_port.get(port, []) if r["portcalls"] is not None],
            key=lambda r: parse_as_of(r["date"]) or oldest, reverse=True,
        )
        if not sorted_rows:
            signals[port] = "Unknown"
            reasons[port] = f"No PortWatch rows for {port} in the last 14 days."
            continue
        if len(sorted_rows) < 2:
            signals[port] = "Unknown"
            reasons[port] = (f"Only 1 day of PortWatch data for {port} in the last 14 days; "
                             "at least 2 are needed to compare.")
            continue
        recent   = sorted_rows[0]["portcalls"]
        previous = sorted_rows[-1]["portcalls"]
        if previous == 0:
            signals[port] = "Unknown"
            earliest = parse_as_of(sorted_rows[-1]["date"])
            day = f"{earliest.day} {earliest.strftime('%B %Y')}" if earliest else "unknown date"
            reasons[port] = (f"{port} had zero port calls on its earliest day in the window "
                             f"({day}), so there is no baseline to compare against.")
            continue
        pct = ((recent - previous) / previous) * 100
        signals[port] = "Rising" if pct > 5 else ("Easing" if pct < -5 else "Stable")
    return signals, reasons
