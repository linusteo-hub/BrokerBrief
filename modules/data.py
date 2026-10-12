"""
modules/data.py
Handles demo data generation and CSV loading.
Core rule: every row must carry source_name, source_url, updated_at, confidence.

The demo rows below are INVENTED values for exercising the Bunkering Strategy
page. They are labelled SAMPLE_LABEL, carry no source URL, and must never be
attributed to a real source or reach Market Intelligence / the morning brief.
"""

import pandas as pd
from datetime import date

from modules.provenance import SAMPLE_LABEL

REQUIRED_COLUMNS = [
    "date", "signal_type", "market_segment", "route_or_port",
    "current_value", "previous_value", "unit", "source_name",
    "source_url", "updated_at", "confidence", "notes",
]

def _build_sample_data() -> pd.DataFrame:
    today = date.today().isoformat()
    rows = [
        # FREIGHT
        {"date": today, "signal_type": "freight", "market_segment": "Capesize",
         "route_or_port": "W Australia / China (iron ore)",
         "current_value": 9.42, "previous_value": 9.10, "unit": "USD/MT",
         "source_name": SAMPLE_LABEL, "source_url": None,
         "updated_at": today, "confidence": 0.92,
         "notes": "Invented demo value."},
        {"date": today, "signal_type": "freight", "market_segment": "Panamax",
         "route_or_port": "Continent / Far East",
         "current_value": 13850, "previous_value": 13200, "unit": "USD/day",
         "source_name": SAMPLE_LABEL, "source_url": None,
         "updated_at": today, "confidence": 0.90,
         "notes": "Invented demo value."},
        {"date": today, "signal_type": "freight", "market_segment": "VLCC",
         "route_or_port": "Middle East Gulf / China",
         "current_value": 42500, "previous_value": 44100, "unit": "USD/day",
         "source_name": SAMPLE_LABEL, "source_url": None,
         "updated_at": today, "confidence": 0.88,
         "notes": "Invented demo value."},
        # BUNKER
        {"date": today, "signal_type": "bunker", "market_segment": "VLSFO",
         "route_or_port": "Singapore", "current_value": 615, "previous_value": 632,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.95, "notes": "Invented demo value."},
        {"date": today, "signal_type": "bunker", "market_segment": "VLSFO",
         "route_or_port": "Rotterdam", "current_value": 647, "previous_value": 658,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.93, "notes": "Invented demo value."},
        {"date": today, "signal_type": "bunker", "market_segment": "VLSFO",
         "route_or_port": "Fujairah", "current_value": 598, "previous_value": 612,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.92, "notes": "Invented demo value."},
        {"date": today, "signal_type": "bunker", "market_segment": "MGO",
         "route_or_port": "Singapore", "current_value": 855, "previous_value": 870,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.94, "notes": "Invented demo value."},
        {"date": today, "signal_type": "bunker", "market_segment": "MGO",
         "route_or_port": "Fujairah", "current_value": 872, "previous_value": 868,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.88, "notes": "Invented demo value."},
        {"date": today, "signal_type": "bunker", "market_segment": "IFO380",
         "route_or_port": "Singapore", "current_value": 482, "previous_value": 495,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.90, "notes": "Invented demo value."},
        {"date": today, "signal_type": "bunker", "market_segment": "IFO380",
         "route_or_port": "Houston", "current_value": 498, "previous_value": 492,
         "unit": "USD/MT", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.87, "notes": "Invented demo value."},
        # CONGESTION
        {"date": today, "signal_type": "congestion", "market_segment": "Bulk",
         "route_or_port": "Port Hedland", "current_value": 18, "previous_value": 17,
         "unit": "vessels at anchor", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.80, "notes": "Invented demo value."},
        {"date": today, "signal_type": "congestion", "market_segment": "Container",
         "route_or_port": "Singapore", "current_value": 52, "previous_value": 49,
         "unit": "vessels at anchor", "source_name": SAMPLE_LABEL,
         "source_url": None, "updated_at": today,
         "confidence": 0.85, "notes": "Invented demo value."},
    ]
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def is_sample(df: pd.DataFrame) -> pd.Series:
    """True for each demo row (invented values)."""
    if df is None or "source_name" not in df.columns:
        return pd.Series(dtype=bool)
    return df["source_name"].astype(str) == SAMPLE_LABEL


def real_rows(df: pd.DataFrame) -> pd.DataFrame:
    """The rows that are not demo data. Market Intelligence uses only these."""
    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    return df[~is_sample(df)]


def load_data(source: str = "none", file_obj=None) -> pd.DataFrame:
    if source == "none":
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    if source == "sample":
        return _build_sample_data()
    if source == "csv" and file_obj is not None:
        df = pd.read_csv(file_obj)
        df["current_value"] = pd.to_numeric(df["current_value"], errors="coerce")
        df["previous_value"] = pd.to_numeric(df["previous_value"], errors="coerce")
        df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
        return df
    raise ValueError(f"Unknown data source: {source}")
