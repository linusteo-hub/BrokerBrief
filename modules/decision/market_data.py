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

import math

import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from modules.provenance import MANUAL_ENTRY_MAX_AGE, SAMPLE_LABEL, Provenance, QualityTier, parse_as_of


# CSV `market_segment` text that counts as each fuel grade. Matched as the
# WHOLE segment (case and spacing ignored), never as a substring: "ULSFO"
# contains "LSFO" and "VLSFO 380CST" contains "380CST", and neither is the
# grade the substring suggests. A viscosity label alone ("380CST") is not
# accepted, because VLSFO is sold at 380 cSt too. Anything not listed here
# (ULSFO, LSMGO, MDO, …) is a different product and is never used.
GRADE_ALIASES = {
    "VLSFO": ("VLSFO", "VLSFO 0.5%", "LSFO"),
    "MGO":   ("MGO",),
    "HSFO":  ("HSFO", "HSFO 3.5%", "IFO380", "IFO 380"),
}


def grade_of(segment) -> Optional[str]:
    """The fuel grade a CSV `market_segment` value names, or None."""
    text = " ".join(str(segment or "").upper().split())
    for grade, aliases in GRADE_ALIASES.items():
        if text in aliases:
            return grade
    return None


def valid_price(value) -> Optional[float]:
    """A usable price: a finite number above zero. Anything else (blank, NaN,
    zero, negative, text) is None, i.e. "no price", everywhere in the engine."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def assemble_market_data(
    df: Optional[pd.DataFrame],
    eia_data: Optional[dict],
    portwatch_data: Optional[dict],
    fujairah_price_override: Optional[float] = None,
    simulate_fujairah_missing: bool = False,
    fuel_grade: str = "VLSFO",
    singapore_price_override: Optional[float] = None,
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
        fuel_grade: The scenario's fuel grade ("VLSFO", "MGO" or "HSFO"). Prices
                    are read for this grade only; another grade's price is never
                    substituted.
        singapore_price_override: Manually supplied Singapore price (user input).

    Each port's entry in `bunker_prices` is {"price": ..., "price_prev": ...}
    for the selected grade, or {} when no price is available.
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
        "fuel_grade":          fuel_grade,
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
    # Where several rows give a price for the same port and grade, the one with
    # the latest `updated_at` is used (a row with no readable date loses to one
    # with a date; otherwise the later row in the file wins).
    if df is not None and not df.empty and "signal_type" in df.columns:
        chosen: dict[str, tuple] = {}      # port -> (as_of or None, row order, current, previous, row)
        bunker_df = df[df["signal_type"] == "bunker"]
        for order, (_, row) in enumerate(bunker_df.iterrows()):
            port = str(row.get("route_or_port", "")).strip().title()
            if port not in ("Singapore", "Fujairah"):
                continue
            if grade_of(row.get("market_segment")) != fuel_grade:
                continue
            current = valid_price(row.get("current_value"))
            if current is None:
                continue                    # blank, zero, negative or non-numeric: not a price
            as_of = parse_as_of(row.get("updated_at"))
            rank = (as_of is not None, as_of or datetime.min.replace(tzinfo=timezone.utc), order)
            if port not in chosen or rank > chosen[port][0]:
                chosen[port] = (rank, current, valid_price(row.get("previous_value")), as_of, row)
        for port, (_, current, previous, as_of, row) in chosen.items():
            market_data["bunker_prices"][port]["price"] = current
            if previous is not None:
                market_data["bunker_prices"][port]["price_prev"] = previous
            market_data["provenance"][f"{port} {fuel_grade}"] = Provenance(
                source_name=str(row.get("source_name") or "CSV manual entry"),
                source_url=row.get("source_url"),
                as_of=as_of,
                retrieved_at=datetime.now(timezone.utc),
                # Label only: demo rows are invented, so they must not be recorded
                # as analyst-entered. Values and tier are unchanged; scoring unaffected.
                licence=(SAMPLE_LABEL if row.get("source_name") == SAMPLE_LABEL
                         else "Internal — analyst-entered"),
                quality_tier=QualityTier.MANUAL_ENTRY,
                max_age=MANUAL_ENTRY_MAX_AGE,
            )

    # ── Overrides & simulation flags ─────────────────────────────────────────
    # A user-entered price replaces the CSV price for that port. It has no
    # previous value, so it takes no part in the signal-agreement checks.
    # The caller must only pass a price the user entered *for this grade*.
    for port, override in (("Singapore", singapore_price_override), ("Fujairah", fujairah_price_override)):
        override = valid_price(override)
        if override is None:
            continue
        market_data["bunker_prices"][port] = {"price": override}
        now = datetime.now(timezone.utc)
        market_data["provenance"][f"{port} {fuel_grade}"] = Provenance(
            source_name="User override",
            source_url=None,
            as_of=now,
            retrieved_at=now,
            licence="n/a",
            quality_tier=QualityTier.USER_OVERRIDE,
            max_age=None,
        )

    # The "simulate missing" demo flag wins over any price, typed or loaded.
    if simulate_fujairah_missing:
        market_data["bunker_prices"]["Fujairah"] = {}
        market_data["provenance"][f"Fujairah {fuel_grade}"] = None

    # Flag any missing prices in provenance
    for port in ("Singapore", "Fujairah"):
        if "price" not in market_data["bunker_prices"][port]:
            market_data["provenance"][f"{port} {fuel_grade}"] = None

    return market_data
