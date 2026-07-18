"""
modules/signals.py
Core signal engine. Derives directional signals and market tone from source-backed data.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import pandas as pd


@dataclass
class SignalResult:
    sufficient: bool = False
    freight_direction: str = "Flat"
    bunker_direction: str = "Flat"
    congestion_direction: str = "Stable"
    market_tone: str = "Mixed"
    key_route: str = "–"
    main_news: str = "No news signal available."
    signal_table: List[Dict] = field(default_factory=list)
    avg_confidence: float = 0.0


def _pct_change(current, previous) -> Optional[float]:
    try:
        if previous == 0:
            return None
        return ((current - previous) / abs(previous)) * 100
    except (TypeError, ZeroDivisionError):
        return None


def _freight_dir(pct: float) -> str:
    if pct > 1.0:   return "Up"
    if pct < -1.0:  return "Down"
    return "Flat"


def _bunker_dir(pct: float) -> str:
    if pct > 1.0:   return "Up"
    if pct < -1.0:  return "Down"
    return "Flat"


def _congestion_dir(pct: float) -> str:
    if pct > 5.0:   return "Rising"
    if pct < -5.0:  return "Easing"
    return "Stable"


def _market_tone(freight: str, bunker: str, congestion: str) -> str:
    rules = {
        ("Up",   "Down", "Stable"):  "Bullish",
        ("Up",   "Down", "Easing"):  "Bullish",
        ("Up",   "Down", "Rising"):  "Cautiously Bullish",
        ("Up",   "Up",   "Rising"):  "Mixed",
        ("Down", "Up",   "Rising"):  "Bearish",
        ("Down", "Down", "Easing"):  "Soft Demand / Mixed",
        ("Flat", "Flat", "Stable"):  "Neutral",
    }
    return rules.get((freight, bunker, congestion), "Mixed")


def _rows_have_sources(df: pd.DataFrame) -> bool:
    required = ["source_name", "source_url", "updated_at", "confidence"]
    for col in required:
        if col not in df.columns:
            return False
    sourced = df.dropna(subset=required)
    sourced = sourced[sourced["source_name"].astype(str).str.strip() != ""]
    return len(sourced) > 0


def compute_signals(df: pd.DataFrame) -> SignalResult:
    result = SignalResult()
    if df is None or df.empty:
        return result
    if not _rows_have_sources(df):
        return result

    sourced_df = df.dropna(subset=["source_name", "source_url", "updated_at", "confidence"]).copy()
    sourced_df = sourced_df[sourced_df["source_name"].astype(str).str.strip() != ""]
    result.avg_confidence = pd.to_numeric(sourced_df["confidence"], errors="coerce").mean() or 0.0

    signal_table_rows = []

    # FREIGHT
    freight_df = sourced_df[sourced_df["signal_type"] == "freight"].copy()
    freight_pcts = []
    for _, row in freight_df.iterrows():
        pct = _pct_change(
            pd.to_numeric(row["current_value"], errors="coerce"),
            pd.to_numeric(row["previous_value"], errors="coerce"),
        )
        if pct is None:
            continue
        freight_pcts.append(pct)
        if result.key_route == "–":
            result.key_route = str(row.get("route_or_port", "–"))
        signal_table_rows.append({
            "Signal": f"{row['market_segment']} freight",
            "Route / Port": str(row.get("route_or_port", "–")),
            "Current Value": f"{row['current_value']:,.0f}",
            "Previous Value": f"{row['previous_value']:,.0f}",
            "Pct Change": pct,
            "Direction": _freight_dir(pct),
            "Source": str(row.get("source_name", "–")),
            "Updated At": str(row.get("updated_at", "–")),
            "Confidence": pd.to_numeric(row.get("confidence"), errors="coerce") or 0.0,
            "Notes": str(row.get("notes", "")),
        })
    if freight_pcts:
        result.freight_direction = _freight_dir(sum(freight_pcts) / len(freight_pcts))

    # BUNKERS
    bunker_df = sourced_df[sourced_df["signal_type"] == "bunker"].copy()
    bunker_pcts = []
    for _, row in bunker_df.iterrows():
        pct = _pct_change(
            pd.to_numeric(row["current_value"], errors="coerce"),
            pd.to_numeric(row["previous_value"], errors="coerce"),
        )
        if pct is None:
            continue
        bunker_pcts.append(pct)
        signal_table_rows.append({
            "Signal": f"{row['market_segment']} bunker",
            "Route / Port": str(row.get("route_or_port", "–")),
            "Current Value": f"{row['current_value']:,.0f}",
            "Previous Value": f"{row['previous_value']:,.0f}",
            "Pct Change": pct,
            "Direction": _bunker_dir(pct),
            "Source": str(row.get("source_name", "–")),
            "Updated At": str(row.get("updated_at", "–")),
            "Confidence": pd.to_numeric(row.get("confidence"), errors="coerce") or 0.0,
            "Notes": str(row.get("notes", "")),
        })
    if bunker_pcts:
        result.bunker_direction = _bunker_dir(sum(bunker_pcts) / len(bunker_pcts))

    # CONGESTION
    cong_df = sourced_df[sourced_df["signal_type"] == "congestion"].copy()
    cong_pcts = []
    for _, row in cong_df.iterrows():
        pct = _pct_change(
            pd.to_numeric(row["current_value"], errors="coerce"),
            pd.to_numeric(row["previous_value"], errors="coerce"),
        )
        if pct is None:
            continue
        cong_pcts.append(pct)
        signal_table_rows.append({
            "Signal": f"{row['market_segment']} congestion",
            "Route / Port": str(row.get("route_or_port", "–")),
            "Current Value": f"{row['current_value']:,.0f}",
            "Previous Value": f"{row['previous_value']:,.0f}",
            "Pct Change": pct,
            "Direction": _congestion_dir(pct),
            "Source": str(row.get("source_name", "–")),
            "Updated At": str(row.get("updated_at", "–")),
            "Confidence": pd.to_numeric(row.get("confidence"), errors="coerce") or 0.0,
            "Notes": str(row.get("notes", "")),
        })
    if cong_pcts:
        result.congestion_direction = _congestion_dir(sum(cong_pcts) / len(cong_pcts))

    # NEWS
    news_df = sourced_df[sourced_df["signal_type"] == "news"].copy()
    if not news_df.empty:
        result.main_news = str(news_df.iloc[0].get("notes", "No news signal available."))

    result.market_tone = _market_tone(
        result.freight_direction, result.bunker_direction, result.congestion_direction
    )
    result.signal_table = signal_table_rows
    result.sufficient = True
    return result
