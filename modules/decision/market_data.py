"""
modules/decision/market_data.py

Assembles market data from existing BrokerBrief feeds into the format
expected by the decision engine (evaluation + confidence models).

Distinguishes clearly between:
  LIVE DATA (EIA, Portwatch)
  MANUAL DATA (CSV bunker prices)
  MISSING DATA (flagged, never invented)

Principle: NO SOURCE, NO CERTAINTY.
If a feed fails, we flag it and lower confidence — we never invent values.
"""

import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from modules.provenance import MANUAL_ENTRY_MAX_AGE, SAMPLE_LABEL, Provenance, QualityTier, parse_as_of


def assemble_market_data(
    df: Optional[pd.DataFrame],
    eia_data: Optional[dict],
    portwatch_data: Optional[dict],
    fujairah_price_override: Optional[float] = None,
    simulate_fujairah_missing: bool = False,
) -> dict:
    """
    Builds the market_data dict consumed by the evaluation and confidence models.

    Args:
        df: The manual CSV market DataFrame (bunker rows used for prices).
        eia_data: Output of modules.eia.fetch_all() or None.
        portwatch_data: Output of modules.portwatch.fetch_port_activity() or None.
        fujairah_price_override: Manually supplied Fujairah price (user input).
        simulate_fujairah_missing: For demo Scenario 3 — treat Fujairah price
                                    as unavailable regardless of CSV contents.
    """
    market_data = {
        "brent_available":     False,
        "brent_direction":     None,
        "brent_pct_change":    0.0,
        "brent_price":         None,
        "brent_date":          None,
        "forecast_available":  False,
        "forecast_rows":       [],
        "portwatch_available": False,
        "congestion_signals":  {},
        "congestion_reasons":  {},   # port -> why its signal is "Unknown"
        "bunker_prices":       {"Singapore": {}, "Fujairah": {}},
        "provenance":          {},   # Dict[str, Optional[Provenance]] — one entry per input
    }

    # ── EIA (LIVE) ───────────────────────────────────────────────────────────
    if eia_data:
        spot = eia_data.get("spot", {})
        if spot.get("success"):
            market_data["brent_available"]  = True
            market_data["brent_direction"]  = spot["direction"]
            market_data["brent_pct_change"] = spot["pct_change"]
            market_data["brent_price"]      = spot["current_value"]
            market_data["brent_date"]       = spot["latest_date"]
            market_data["provenance"]["Brent spot"] = spot["provenance"]

        fcast = eia_data.get("forecast", {})
        if fcast.get("success"):
            market_data["forecast_available"] = True
            market_data["forecast_rows"]      = fcast["forecast_rows"]
            market_data["provenance"]["Brent forecast"] = fcast["provenance"]

    if not market_data["brent_available"]:
        market_data["provenance"]["Brent spot"] = None

    # ── Portwatch (LIVE) ──────────────────────────────────────────────────────
    if portwatch_data and portwatch_data.get("success"):
        market_data["portwatch_available"] = True
        market_data["congestion_signals"]  = portwatch_data["congestion_signals"]
        market_data["congestion_reasons"]  = portwatch_data.get("congestion_reasons", {})
        market_data["provenance"]["Port congestion"] = portwatch_data["provenance"]
    else:
        market_data["provenance"]["Port congestion"] = None

    # ── Bunker prices (MANUAL CSV) ────────────────────────────────────────────
    if df is not None and not df.empty and "signal_type" in df.columns:
        bunker_df = df[df["signal_type"] == "bunker"].copy()
        for _, row in bunker_df.iterrows():
            port  = str(row.get("route_or_port", "")).strip()
            grade = str(row.get("market_segment", "")).strip().upper()
            if port not in ("Singapore", "Fujairah"):
                continue
            if "VLSFO" not in grade and "LSFO" not in grade:
                continue
            try:
                current  = float(row["current_value"])
                previous = float(row["previous_value"])
            except (ValueError, TypeError):
                continue
            market_data["bunker_prices"][port]["VLSFO"]      = current
            market_data["bunker_prices"][port]["VLSFO_prev"] = previous
            market_data["provenance"][f"{port} VLSFO"] = Provenance(
                source_name=str(row.get("source_name") or "CSV manual entry"),
                source_url=row.get("source_url"),
                as_of=parse_as_of(row.get("updated_at")),
                retrieved_at=datetime.now(timezone.utc),
                # Label only: demo rows are invented, so they must not be recorded
                # as analyst-entered. Values and tier are unchanged; scoring unaffected.
                licence=(SAMPLE_LABEL if row.get("source_name") == SAMPLE_LABEL
                         else "Internal — analyst-entered"),
                quality_tier=QualityTier.MANUAL_ENTRY,
                max_age=MANUAL_ENTRY_MAX_AGE,
            )

    # ── Overrides & simulation flags ─────────────────────────────────────────
    if fujairah_price_override is not None:
        market_data["bunker_prices"]["Fujairah"]["VLSFO"] = fujairah_price_override
        now = datetime.now(timezone.utc)
        market_data["provenance"]["Fujairah VLSFO"] = Provenance(
            source_name="User override",
            source_url=None,
            as_of=now,
            retrieved_at=now,
            licence="n/a",
            quality_tier=QualityTier.USER_OVERRIDE,
            max_age=None,
        )

    if simulate_fujairah_missing:
        market_data["bunker_prices"]["Fujairah"].pop("VLSFO", None)
        market_data["bunker_prices"]["Fujairah"].pop("VLSFO_prev", None)
        market_data["provenance"]["Fujairah VLSFO"] = None

    # Flag any missing prices in provenance
    if "VLSFO" not in market_data["bunker_prices"]["Singapore"]:
        market_data["provenance"]["Singapore VLSFO"] = None
    if "VLSFO" not in market_data["bunker_prices"]["Fujairah"]:
        market_data["provenance"].setdefault("Fujairah VLSFO", None)

    return market_data
