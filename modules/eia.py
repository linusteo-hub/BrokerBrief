"""
modules/eia.py
Fetches live Brent crude spot prices and forward forecasts from EIA API.
No API key = returns success:False gracefully. App falls back to sample data.
"""

import requests
from datetime import date

EIA_BASE = "https://api.eia.gov/v2"


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
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_brent_forecast(api_key: str) -> dict:
    # Dynamic start date — always current month
    start = date.today().strftime("%Y-%m")
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
            "updated_at":    date.today().isoformat(),
            "confidence":    0.80,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def fetch_all(api_key: str) -> dict:
    return {
        "spot":     fetch_brent_spot(api_key),
        "forecast": fetch_brent_forecast(api_key),
    }
