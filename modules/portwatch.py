"""
modules/portwatch.py
Fetches port activity data from IMF Portwatch via ArcGIS FeatureServer.
No API key required.
"""

import requests
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict

from modules.provenance import (
    PORTWATCH_MAX_AGE, QualityTier, SourceInfo, parse_as_of, stamp, utc_date, utc_today,
)

PORTWATCH_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/"
    "ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query"
)

CHOKEPOINTS_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/"
    "ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"
)
LAYER_URLS = {"ports": PORTWATCH_URL, "chokepoints": CHOKEPOINTS_URL}

TARGET_PORTS = ["Singapore", "Rotterdam", "Fujairah", "Port Hedland", "Houston"]

# IMF terms (https://www.imf.org/en/about/copyright-and-terms) allow reuse and
# publication with a citation, and require stating any material transformation;
# commercial reuse and automated bulk download need IMF permission. Everything
# BrokerBrief shows from PortWatch is derived (direction labels, totals,
# changes), hence "calculations based on". Show it wherever PortWatch data is.
PORTWATCH_CREDIT = ("BrokerBrief calculations based on data from International Monetary Fund, "
                    "PortWatch, https://portwatch.imf.org")

# The app's port name -> PortWatch's `portname`, where they differ. This is the
# only place the mapping lives. PortWatch names the port "Houston (US-TX)"
# (portid port481); querying plain "Houston" returned no rows, so Houston was
# silently missing. Checked against PortWatch_ports_database on 12-10-2026: the
# other target ports match exactly.
PORTWATCH_NAMES = {"Houston": "Houston (US-TX)"}
APP_NAMES = {pw: app for app, pw in PORTWATCH_NAMES.items()}

PORTWATCH = SourceInfo(
    name="IMF Portwatch",
    url="https://portwatch.imf.org",
    licence="IMF copyright and terms (reuse with credit; commercial reuse needs permission)",
    quality_tier=QualityTier.LIVE_API,
    max_age=PORTWATCH_MAX_AGE,
)


def fetch_port_activity() -> dict:
    cutoff = (utc_today() - timedelta(days=14)).strftime("%Y-%m-%d")
    port_list = ", ".join(f"'{PORTWATCH_NAMES.get(p, p)}'" for p in TARGET_PORTS)
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
                "portname":           APP_NAMES.get(f["attributes"].get("portname"), f["attributes"].get("portname")),
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
            "updated_at":         utc_today().isoformat(),
            "confidence":         0.80,
            # Rows are ordered `portname, date DESC` (grouped per port, not globally
            # sorted) — as_of must be an explicit max() over all rows, not rows[0].
            "provenance":         stamp(PORTWATCH, as_of=latest_as_of),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_daily_rows(layer: str, portids: list, start: str, fields: list, get=requests.get) -> dict:
    """Raw daily rows from one PortWatch layer ("ports" or "chokepoints") for the
    given portids from `start` (YYYY-MM-DD). Returns {"success": True, "rows":
    [attribute dicts]} or {"success": False, "error": ...}.

    ArcGIS reports query errors with HTTP 200 and an "error" body, and silently
    truncates large results (exceededTransferLimit); both count as failures.
    `get` is injectable; only network and response-shape errors are caught."""
    id_list = ", ".join(f"'{p}'" for p in portids)
    params = {
        "where":             f"portid IN ({id_list}) AND date >= DATE '{start}'",
        "outFields":         ",".join(fields),
        "orderByFields":     "portid,date DESC",
        "returnGeometry":    "false",
        "resultRecordCount": 2000,
        "f":                 "json",
    }
    try:
        response = get(LAYER_URLS[layer], params=params, timeout=20)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise ValueError(f"ArcGIS error: {body['error'].get('message')}")
        if body.get("exceededTransferLimit"):
            raise ValueError("ArcGIS truncated the result (exceededTransferLimit)")
        return {"success": True, "rows": [f["attributes"] for f in body["features"]]}
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
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
            earliest = utc_date(sorted_rows[-1]["date"])
            day = f"{earliest.day} {earliest.strftime('%B %Y')}" if earliest else "unknown date"
            reasons[port] = (f"{port} had zero port calls on its earliest day in the window "
                             f"({day}), so there is no baseline to compare against.")
            continue
        pct = ((recent - previous) / previous) * 100
        signals[port] = "Rising" if pct > 5 else ("Easing" if pct < -5 else "Stable")
    return signals, reasons
