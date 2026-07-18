"""
modules/decision/evaluation_engine.py

Commercial Evaluation Engine — Layer 2 of the BrokerBrief decision pipeline.

Only operates on options that passed the Constraint Engine.
Scores each option using transparent, weighted commercial logic.
Weights are visible, configurable, and logically defensible.

Principle: The scoring model does not need to be perfect for the POC.
It needs to be transparent, deterministic, and easy to improve later.
"""

from typing import List, Optional, Dict
from modules.decision.options import BunkeringOption
from modules.decision.scenario import BunkeringScenario, RiskProfile
from modules.decision.constraint_engine import CONGESTION_WAIT_HOURS, PORT_BUNKERING_TIME_HOURS


# ── Risk profile weight sets ──────────────────────────────────────────────────
# Weights sum to 1.0. Clearly visible — users can see why options rank as they do.

WEIGHT_SETS = {
    RiskProfile.CONSERVATIVE: {
        "expected_cost":    0.30,
        "operational_risk": 0.45,
        "schedule_risk":    0.25,
    },
    RiskProfile.BALANCED: {
        "expected_cost":    0.40,
        "operational_risk": 0.35,
        "schedule_risk":    0.25,
    },
    RiskProfile.COST_FOCUSED: {
        "expected_cost":    0.60,
        "operational_risk": 0.25,
        "schedule_risk":    0.15,
    },
}


def _score_expected_cost(
    option: BunkeringOption,
    market_data: dict,
) -> tuple[float, str]:
    """
    Score 0–100 based on expected fuel cost relative to other ports.
    Higher score = lower cost = better commercial outcome.

    Returns (score, explanation).
    """
    port = option.port
    prices = market_data.get("bunker_prices", {})

    sg_price  = prices.get("Singapore",  {}).get("VLSFO")
    fuj_price = prices.get("Fujairah",   {}).get("VLSFO")

    # EIA crude direction as macro signal
    brent_direction = market_data.get("brent_direction", "Flat")
    brent_pct       = market_data.get("brent_pct_change", 0.0)

    if port == "Singapore":
        if sg_price is None:
            # Price unavailable — neutral score, flag for confidence model
            return 50.0, "Singapore price unavailable — neutral score applied."
        if fuj_price is None:
            # Can't compare — assume neutral
            score = 55.0
            note = "Fujairah price unavailable for comparison."
        elif sg_price <= fuj_price:
            diff = fuj_price - sg_price
            score = min(100.0, 65.0 + (diff / fuj_price) * 100)
            note = f"Singapore VLSFO (${sg_price}/MT) is ${diff:.0f}/MT cheaper than Fujairah."
        else:
            diff = sg_price - fuj_price
            score = max(20.0, 50.0 - (diff / sg_price) * 60)
            note = f"Singapore VLSFO (${sg_price}/MT) is ${diff:.0f}/MT more expensive than Fujairah."

        # Adjust for bullish crude (buy now before prices rise)
        if brent_direction == "Up" and brent_pct > 1.0:
            score = min(100.0, score + 10.0)
            note += f" Crude trending up ({brent_pct:+.1f}%) — bunkering now reduces price exposure."
        elif brent_direction == "Down":
            score = max(10.0, score - 8.0)
            note += " Crude softening — waiting may offer modest savings."

    elif port == "Fujairah":
        if fuj_price is None:
            return 50.0, "Fujairah price unavailable — neutral score applied. Confidence reduced."
        if sg_price is None:
            score = 55.0
            note = "Singapore price unavailable for comparison."
        elif fuj_price < sg_price:
            diff = sg_price - fuj_price
            score = min(100.0, 65.0 + (diff / sg_price) * 100)
            note = f"Fujairah VLSFO (${fuj_price}/MT) is ${diff:.0f}/MT cheaper than Singapore."
        else:
            diff = fuj_price - sg_price
            score = max(20.0, 50.0 - (diff / fuj_price) * 60)
            note = f"Fujairah VLSFO (${fuj_price}/MT) is ${diff:.0f}/MT more expensive than Singapore."

        # Bearish crude favours waiting
        if brent_direction == "Down":
            score = min(100.0, score + 8.0)
            note += " Softening crude supports waiting for Fujairah."
        elif brent_direction == "Up" and brent_pct > 1.0:
            score = max(10.0, score - 10.0)
            note += " Rising crude reduces the advantage of delaying bunkering."
    else:
        score = 50.0
        note = "Unknown port."

    # Partial stem adjustment: split cost risk across two stems
    if option.is_partial:
        score = score * 0.9  # Slight penalty for operational complexity
        note += " Partial stem introduces split-cost uncertainty."

    return round(score, 1), note


def _score_operational_risk(
    option: BunkeringOption,
    market_data: dict,
) -> tuple[float, str]:
    """
    Score 0–100. Higher score = lower operational risk = better.
    Considers port congestion, estimated waiting time, and data quality.
    """
    port = option.port
    congestion_signals = market_data.get("congestion_signals", {})
    congestion = congestion_signals.get(port, "Stable")
    est_wait   = CONGESTION_WAIT_HOURS.get(congestion, 8.0)

    if congestion == "Easing":
        score = 85.0
        note  = f"{port} congestion easing — low operational delay risk. Est. wait: {est_wait:.0f}h."
    elif congestion == "Stable":
        score = 70.0
        note  = f"{port} congestion stable. Est. wait: {est_wait:.0f}h."
    elif congestion == "Rising":
        score = 40.0
        note  = f"{port} congestion rising — elevated delay risk. Est. wait: {est_wait:.0f}h."
    else:
        score = 55.0
        note  = f"Congestion data unavailable for {port} — moderate risk assumed."

    # Partial stems carry additional coordination risk
    if option.is_partial:
        score = max(10.0, score - 10.0)
        note += " Partial stem requires two port calls — additional coordination risk."

    return round(score, 1), f"{note} (Congestion estimate — see data sources.)"


def _score_schedule_risk(
    option: BunkeringOption,
    scenario: BunkeringScenario,
    market_data: dict,
) -> tuple[float, str]:
    """
    Score 0–100. Higher score = lower schedule risk = better.
    """
    port = option.port
    congestion_signals = market_data.get("congestion_signals", {})
    congestion = congestion_signals.get(port, "Stable")
    est_wait   = CONGESTION_WAIT_HOURS.get(congestion, 8.0)
    bunkering  = PORT_BUNKERING_TIME_HOURS.get(port, 8.0)
    total_time = est_wait + bunkering
    flex       = scenario.schedule_flexibility_hours

    if flex <= 0:
        score = 30.0
        note  = "No schedule flexibility — any delay creates risk."
    else:
        margin = flex - total_time
        if margin > 12:
            score = 90.0
            note  = f"Comfortable schedule margin ({margin:.0f}h buffer)."
        elif margin > 0:
            score = 60.0 + (margin / 12) * 20
            note  = f"Adequate schedule margin ({margin:.0f}h buffer)."
        else:
            score = max(15.0, 40.0 + margin * 2)
            note  = f"Schedule tight — estimated port time exceeds flexibility by {abs(margin):.0f}h."

    if option.is_partial:
        score = max(10.0, score - 15.0)
        note += " Two-port strategy increases schedule exposure."

    return round(score, 1), note


def score_options(
    options: List[BunkeringOption],
    scenario: BunkeringScenario,
    market_data: dict,
) -> List[BunkeringOption]:
    """
    Scores all feasible options and ranks them.
    Infeasible options are skipped.
    Adds score breakdown to each option for transparency.
    """
    weights = WEIGHT_SETS.get(scenario.risk_profile, WEIGHT_SETS[RiskProfile.BALANCED])

    scored = []
    for option in options:
        if not option.is_feasible:
            continue

        cost_score,  cost_note  = _score_expected_cost(option, market_data)
        op_score,    op_note    = _score_operational_risk(option, market_data)
        sched_score, sched_note = _score_schedule_risk(option, scenario, market_data)

        composite = (
            cost_score  * weights["expected_cost"]
            + op_score  * weights["operational_risk"]
            + sched_score * weights["schedule_risk"]
        )

        option.score = round(composite, 1)
        option._score_breakdown = {
            "expected_cost":    {"score": cost_score,  "note": cost_note,  "weight": weights["expected_cost"]},
            "operational_risk": {"score": op_score,    "note": op_note,    "weight": weights["operational_risk"]},
            "schedule_risk":    {"score": sched_score, "note": sched_note, "weight": weights["schedule_risk"]},
            "weights":          weights,
        }
        scored.append(option)

    # Rank by composite score descending
    scored.sort(key=lambda o: o.score or 0, reverse=True)
    for i, opt in enumerate(scored):
        opt.rank = i + 1

    # Write ranks back into the full options list
    ranked_ids = {o.id: o.rank for o in scored}
    for option in options:
        if option.id in ranked_ids:
            option.rank = ranked_ids[option.id]

    return options
