"""
modules/decision/confidence_model.py

Confidence Model — Layer 4 of the BrokerBrief decision pipeline.

Three components:
  A. Data Quality      — how fresh and complete is the market data?
  B. Signal Agreement  — are the market signals pointing in the same direction?
  C. Scenario Completeness — how much context did the user provide?

All deductions are explicit and shown to the user.
The confidence score is deterministic — no random values, no opaque models.
"""

from datetime import datetime, date
from typing import Iterable, Optional
from modules.decision.scenario import BunkeringScenario, FuelAvailability


# ── A. Data Quality ───────────────────────────────────────────────────────────

def compute_data_quality(market_data: dict) -> dict:
    """
    Assesses the quality and freshness of market data.
    Returns score (0-100) and list of factors that affected it.
    """
    score = 100.0
    factors = []
    positive = []

    # EIA Brent spot
    if market_data.get("brent_available"):
        brent_date = market_data.get("brent_date")
        if brent_date:
            try:
                days_old = (date.today() - date.fromisoformat(str(brent_date))).days
                if days_old <= 1:
                    positive.append("EIA Brent spot price current (updated today / yesterday).")
                elif days_old <= 3:
                    score -= 5.0
                    factors.append(f"EIA Brent spot data is {days_old} days old. (−5)")
                else:
                    score -= 15.0
                    factors.append(f"EIA Brent spot data is {days_old} days old — stale. (−15)")
            except Exception:
                score -= 10.0
                factors.append("EIA Brent date could not be parsed. (−10)")
    else:
        score -= 20.0
        factors.append("EIA Brent spot price unavailable. (−20)")

    # EIA forecast
    if market_data.get("forecast_available"):
        positive.append("EIA forward forecast available.")
    else:
        score -= 10.0
        factors.append("EIA Brent forecast unavailable. (−10)")

    # Portwatch congestion
    if market_data.get("portwatch_available"):
        positive.append("IMF Portwatch congestion data available.")
    else:
        score -= 15.0
        factors.append("IMF Portwatch congestion data unavailable. (−15)")

    # Singapore bunker price
    sg_price = market_data.get("bunker_prices", {}).get("Singapore", {}).get("VLSFO")
    if sg_price:
        positive.append("Singapore VLSFO price available.")
    else:
        score -= 15.0
        factors.append("Singapore VLSFO price unavailable — using fallback or estimate. (−15)")

    # Fujairah bunker price
    fuj_price = market_data.get("bunker_prices", {}).get("Fujairah", {}).get("VLSFO")
    if fuj_price:
        positive.append("Fujairah VLSFO price available.")
    else:
        score -= 15.0
        factors.append("Fujairah VLSFO price unavailable — option evaluated at reduced confidence. (−15)")

    return {
        "score":    max(0.0, round(score, 1)),
        "factors":  factors,
        "positive": positive,
    }


# ── B. Signal Agreement ───────────────────────────────────────────────────────

def compute_signal_agreement(market_data: dict) -> dict:
    """
    Checks whether key market signals are pointing in the same direction.
    Agreement increases confidence. Conflict reduces it.
    """
    score = 100.0
    factors = []
    positive = []

    brent_dir   = market_data.get("brent_direction", None)
    sg_price    = market_data.get("bunker_prices", {}).get("Singapore", {}).get("VLSFO")
    sg_prev     = market_data.get("bunker_prices", {}).get("Singapore", {}).get("VLSFO_prev")
    fuj_price   = market_data.get("bunker_prices", {}).get("Fujairah",  {}).get("VLSFO")
    fuj_prev    = market_data.get("bunker_prices", {}).get("Fujairah",  {}).get("VLSFO_prev")
    cong_sg     = market_data.get("congestion_signals", {}).get("Singapore", None)
    cong_fuj    = market_data.get("congestion_signals", {}).get("Fujairah", None)

    signals_available = 0
    signals_agree     = 0

    # Check crude vs Singapore bunker direction
    if brent_dir and sg_price and sg_prev:
        sg_dir = "Up" if sg_price > sg_prev else ("Down" if sg_price < sg_prev else "Flat")
        signals_available += 1
        if brent_dir == sg_dir:
            signals_agree += 1
            positive.append(f"Brent ({brent_dir}) and Singapore VLSFO ({sg_dir}) moving in the same direction.")
        elif brent_dir != "Flat" and sg_dir != "Flat":
            score -= 15.0
            factors.append(f"Brent trending {brent_dir} but Singapore VLSFO trending {sg_dir} — signal conflict. (−15)")

    # Check Singapore vs Fujairah direction
    if sg_price and sg_prev and fuj_price and fuj_prev:
        sg_dir  = "Up" if sg_price  > sg_prev  else ("Down" if sg_price  < sg_prev  else "Flat")
        fuj_dir = "Up" if fuj_price > fuj_prev else ("Down" if fuj_price < fuj_prev else "Flat")
        signals_available += 1
        if sg_dir == fuj_dir:
            signals_agree += 1
            positive.append(f"Singapore and Fujairah VLSFO moving in the same direction ({sg_dir}).")
        elif sg_dir != "Flat" and fuj_dir != "Flat":
            score -= 10.0
            factors.append(f"Singapore VLSFO ({sg_dir}) and Fujairah VLSFO ({fuj_dir}) diverging. (−10)")

    # Congestion signals
    if cong_sg and cong_fuj:
        signals_available += 1
        if cong_sg == cong_fuj:
            signals_agree += 1
            positive.append(f"Port congestion signals aligned ({cong_sg} at both key ports).")
        else:
            score -= 5.0
            factors.append(f"Congestion signals differ: Singapore ({cong_sg}), Fujairah ({cong_fuj}). (−5)")

    if signals_available == 0:
        score = 50.0
        factors.append("Insufficient signal data to assess agreement — moderate uncertainty assumed.")

    return {
        "score":    max(0.0, round(score, 1)),
        "factors":  factors,
        "positive": positive,
    }


# ── C. Scenario Completeness ─────────────────────────────────────────────────

def compute_scenario_completeness(scenario: BunkeringScenario) -> dict:
    """
    Assesses how much context the user provided.
    Delegates to the scenario's own completeness check.
    """
    completeness = scenario.completeness_score()
    base_score   = completeness["score"]

    missing = [
        field for field, provided in completeness["fields"].items()
        if not provided
    ]
    provided = [
        field for field, is_provided in completeness["fields"].items()
        if is_provided
    ]

    factors  = [f"'{f}' not provided — assumption used." for f in missing]
    positive = [f"'{f}' provided." for f in provided]

    return {
        "score":    base_score,
        "factors":  factors,
        "positive": positive,
        "missing":  missing,
    }


# ── Combined Confidence Model ─────────────────────────────────────────────────

# Highest score that still reads as Medium (High starts at 80).
MEDIUM_CAP = 79.0


def unknown_congestion_ports(market_data: dict, ports: Iterable[str]) -> dict:
    """port -> reason, for each of `ports` whose congestion is Unknown or absent."""
    signals = market_data.get("congestion_signals", {})
    reasons = market_data.get("congestion_reasons", {})
    return {
        port: reasons.get(port, f"No PortWatch congestion signal for {port}.")
        for port in sorted(set(ports))
        if signals.get(port) in (None, "Unknown")
    }


def compute_confidence(
    scenario: BunkeringScenario,
    market_data: dict,
    *,
    scored_ports: Iterable[str],
) -> dict:
    """
    Combines the three components into a single Decision Confidence score.
    Returns full breakdown for display in the Decision Workspace.

    `scored_ports` are the ports of the options the engine scored. If any has
    Unknown congestion, confidence is capped at Medium and the reason is shown.
    Required (no default) so a caller cannot silently skip the cap.
    """
    dq = compute_data_quality(market_data)
    sa = compute_signal_agreement(market_data)
    sc = compute_scenario_completeness(scenario)

    # Equal weighting for POC — can be refined
    combined = round(
        (dq["score"] * 0.40)
        + (sa["score"] * 0.30)
        + (sc["score"] * 0.30),
        1
    )

    # Collect all confidence-reducing factors
    all_reductions = dq["factors"] + sa["factors"] + sc["factors"]

    # Cap at Medium when congestion is unknown at any port the engine scored.
    unknown = unknown_congestion_ports(market_data, scored_ports)
    uncapped = combined
    cap_reason = None
    if unknown:
        detail = " ".join(unknown.values())
        cap_reason = (f"Congestion unknown at {', '.join(unknown)}: {detail} "
                      "Confidence is capped at Medium.")
        combined = min(combined, MEDIUM_CAP)
        all_reductions = [cap_reason] + all_reductions

    return {
        "overall":               combined,
        "uncapped_overall":      uncapped,
        "cap_reason":            cap_reason,
        "data_quality":          dq,
        "signal_agreement":      sa,
        "scenario_completeness": sc,
        "reductions":            all_reductions,
        "label": (
            "High"   if combined >= 80 else
            "Medium" if combined >= 60 else
            "Low"
        ),
    }
