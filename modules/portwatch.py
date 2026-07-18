"""
modules/portwatch.py
Fetches port activity data from IMF Portwatch via ArcGIS FeatureServer.
No API key required.
"""

import requests
from datetime import date, timedelta
from collections import defaultdict

PORTWATCH_URL = (
    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/"
    "ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query"
)

TARGET_PORTS = ["Singapore", "Rotterdam", "Fujairah", "Port Hedland", "Houston"]


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
        return {
            "success":            True,
            "ports":              rows,
            "congestion_signals": _compute_congestion(rows),
            "source_name":        "IMF Portwatch",
            "source_url":         "https://portwatch.imf.org",
            "updated_at":         date.today().isoformat(),
            "confidence":         0.80,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _compute_congestion(rows: list) -> dict:
    by_port = defaultdict(list)
    for row in rows:
        by_port[row["portname"]].append(row)

    signals = {}
    for port, port_rows in by_port.items():
        sorted_rows = sorted(
            [r for r in port_rows if r["portcalls"] is not None],
            key=lambda r: r["date"] or 0, reverse=True,
        )
        if len(sorted_rows) < 2:
            signals[port] = "Stable"
            continue
        recent   = sorted_rows[0]["portcalls"]
        previous = sorted_rows[-1]["portcalls"]
        if previous == 0:
            signals[port] = "Stable"
            continue
        pct = ((recent - previous) / previous) * 100
        signals[port] = "Rising" if pct > 5 else ("Easing" if pct < -5 else "Stable")
    return signals
