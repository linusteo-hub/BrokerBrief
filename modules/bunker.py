"""modules/bunker.py — bunker spread analysis."""

import pandas as pd
from typing import Dict, Any

_FUEL_ALIASES = {
    "VLSFO":  ["VLSFO", "VLSFO 0.5%", "LSFO"],
    "MGO":    ["MGO", "MGO 0.1%", "DMA"],
    "IFO380": ["IFO380", "HSFO", "HSFO 3.5%", "IFO 380", "380CST"],
}

def _normalise_fuel(segment: str) -> str:
    s = str(segment).upper().strip()
    for canonical, aliases in _FUEL_ALIASES.items():
        if any(s == a.upper() for a in aliases) or canonical in s:
            return canonical
    return segment


def compute_bunker_spreads(df: pd.DataFrame) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "available": False, "by_fuel": {},
        "largest_spread": 0.0, "largest_spread_fuel": "–", "largest_spread_ports": "–",
    }
    if df is None or df.empty:
        return result

    bunker_df = df[df["signal_type"] == "bunker"].copy()
    if bunker_df.empty:
        return result

    bunker_df["fuel_type"] = bunker_df["market_segment"].apply(_normalise_fuel)
    bunker_df["current_value"] = pd.to_numeric(bunker_df["current_value"], errors="coerce")
    bunker_df = bunker_df.dropna(subset=["current_value", "route_or_port"])
    if bunker_df.empty:
        return result

    result["available"] = True
    max_spread = 0.0

    for fuel_type in ["VLSFO", "MGO", "IFO380"]:
        subset = bunker_df[bunker_df["fuel_type"] == fuel_type]
        if subset.empty:
            continue
        cheapest_row  = subset.loc[subset["current_value"].idxmin()]
        expensive_row = subset.loc[subset["current_value"].idxmax()]
        spread = float(expensive_row["current_value"] - cheapest_row["current_value"])
        result["by_fuel"][fuel_type] = {
            "cheapest_port":        str(cheapest_row["route_or_port"]),
            "cheapest_price":       float(cheapest_row["current_value"]),
            "most_expensive_port":  str(expensive_row["route_or_port"]),
            "most_expensive_price": float(expensive_row["current_value"]),
            "spread":               spread,
        }
        if spread > max_spread:
            max_spread = spread
            result["largest_spread"] = spread
            result["largest_spread_fuel"] = fuel_type
            result["largest_spread_ports"] = (
                f"{cheapest_row['route_or_port']} (cheapest) and "
                f"{expensive_row['route_or_port']} (most expensive)"
            )
    return result
