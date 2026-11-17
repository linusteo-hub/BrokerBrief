"""
modules/eia.py
Fetches live Brent crude spot prices and forward forecasts from EIA API.
No API key = returns success:False gracefully. App falls back to sample data.
"""

import re
import requests
from datetime import date

from modules.provenance import (
    utc_today,
    EIA_FORECAST_MAX_AGE,
    EIA_SPOT_MAX_AGE,
    QualityTier,
    SourceInfo,
    parse_as_of,
    stamp,
)

EIA_BASE = "https://api.eia.gov/v2"

EIA_SPOT = SourceInfo(
    name="EIA",
    url="https://www.eia.gov/opendata/",
    licence="U.S. Government Work (public domain)",
    quality_tier=QualityTier.LIVE_API,
    max_age=EIA_SPOT_MAX_AGE,
)
EIA_FORECAST = SourceInfo(
    name="EIA STEO",
    url="https://www.eia.gov/steo/",
    licence="U.S. Government Work (public domain)",
    quality_tier=QualityTier.LIVE_API,
    max_age=EIA_FORECAST_MAX_AGE,
)


def _redact(message: str) -> str:
    """Request errors quote the URL, which carries the API key. Never let it out."""
    return re.sub(r"api_key=[^&\s]+", "api_key=<redacted>", message)


def fetch_spot_series(api_key: str, series_id: str, start: str, get=requests.get) -> dict:
    """Raw daily rows for one EIA spot-price series (route petroleum/pri/spt),
    newest first, from `start` (YYYY-MM-DD) onwards. Rows are returned as EIA
    sends them (`period`, `value` as a string, `units`, …); parsing and checks
    are the caller's job.

    `get` defaults to requests.get; callers may pass a guarded getter. Only
    network and response-shape errors are turned into {"success": False}; any
    other exception (e.g. a guard refusing the URL) propagates."""
    params = {
        "api_key": api_key,
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": series_id,
        "start": start,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 60,
    }
    try:
        response = get(f"{EIA_BASE}/petroleum/pri/spt/data/", params=params, timeout=15)
        response.raise_for_status()
        rows = response.json()["response"]["data"]
        if not isinstance(rows, list):
            raise TypeError("response.data is not a list")
        return {"success": True, "rows": rows}
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        return {"success": False, "error": _redact(str(e))}


def fetch_brent_spot(api_key: str) -> dict:
    url = (
        f"{EIA_BASE}/petroleum/pri/spt/data/"
        f"?api_key={api_key}"
        "&frequency=daily"
        "&data[0]=value"
        "&facets[series][]=RBRTE"
        "&sort[0][column]=period"
        "&sort[0][direction]=desc"
        "&length=5"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        rows = response.json()["response"]["data"]
        if len(rows) < 2:
            return {"success": False, "error": "Insufficient data"}
        current  = float(rows[0]["value"])
        previous = float(rows[1]["value"])
        pct      = ((current - previous) / previous) * 100
        return {
            "success":        True,
            "current_value":  current,
            "previous_value": previous,
            "pct_change":     round(pct, 2),
            "direction":      "Up" if pct > 1 else ("Down" if pct < -1 else "Flat"),
            "latest_date":    rows[0]["period"],
            "unit":           "USD/bbl",
            "source_name":    "EIA",
            "source_url":     "https://www.eia.gov/opendata/",
            "updated_at":     rows[0]["period"],
            "confidence":     0.95,
            "raw_rows":       rows,
            "provenance":     stamp(EIA_SPOT, as_of=parse_as_of(rows[0]["period"])),
        }
    except Exception as e:
        return {"success": False, "error": _redact(str(e))}


def fetch_brent_forecast(api_key: str) -> dict:
    # Dynamic start date — always current month
    start = utc_today().strftime("%Y-%m")
    url = (
        f"{EIA_BASE}/steo/data/"
        f"?api_key={api_key}"
        "&frequency=monthly"
        "&data[0]=value"
        "&facets[seriesId][]=BREPUUS"
        "&sort[0][column]=period"
        "&sort[0][direction]=asc"
        f"&start={start}"
        "&length=6"
    )
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        rows = response.json()["response"]["data"]
        if not rows:
            return {"success": False, "error": "No forecast data"}
        forecast_rows = [{"month": r["period"], "forecast": float(r["value"]), "unit": "USD/bbl"} for r in rows]
        return {
            "success":       True,
            "nearest_month": forecast_rows[0]["month"],
            "nearest_value": forecast_rows[0]["forecast"],
            "forecast_rows": forecast_rows,
            "source_name":   "EIA STEO",
            "source_url":    "https://www.eia.gov/steo/",
            "updated_at":    utc_today().isoformat(),
            "confidence":    0.80,
            # No publication-vintage field is exposed by this endpoint — forecast_rows
            # carries the forecasted (forward-looking) month, not an observation date,
            # so as_of is deliberately None here rather than derived from it.
            "provenance":    stamp(EIA_FORECAST, as_of=None),
        }
    except Exception as e:
        return {"success": False, "error": _redact(str(e))}


def fetch_all(api_key: str) -> dict:
    return {
        "spot":     fetch_brent_spot(api_key),
        "forecast": fetch_brent_forecast(api_key),
    }
