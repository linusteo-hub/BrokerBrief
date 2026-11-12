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

from datetime import datetime, timezone
from typing import Iterable, Optional
from modules.decision.scenario import BunkeringScenario, FuelAvailability
from modules.provenance import Freshness


# ── A. Data Quality ───────────────────────────────────────────────────────────

# Deduction for an input older than its source's own staleness limit.
STALE_DEDUCTION = 15.0


def _freshness(market_data: dict, key: str, label: str, now: Optional[datetime]):
    """(deduction, factor, positive) for one input, judged by its Provenance:
    the date the *source* reports against that source's own `max_age` limit
    (EIA spot 10 days, PortWatch 14 days, …). So a weekly release is not
    penalised for being a few days old, and a value past its limit always is.
    """
    prov = market_data.get("provenance", {}).get(key)
    state = prov.freshness(now) if prov is not None else Freshness.UNKNOWN
    if state == Freshness.FRESH:
        return 0.0, None, f"{label} is within its freshness limit ({prov.max_age.days} days)."
    if state == Freshness.STALE:
        age_days = ((now or datetime.now(timezone.utc)) - prov.as_of).days
        return (STALE_DEDUCTION,
                f"{label} is {age_days} days old, past its {prov.max_age.days}-day limit — stale. "
                f"(−{STALE_DEDUCTION:.0f})",
                None)
    # UNKNOWN: no source date, or a source with no limit (e.g. a price the user
    # just typed in). Nothing to judge, so nothing is deducted and nothing is claimed.
    return 0.0, None, None


def compute_data_quality(market_data: dict, now: Optional[datetime] = None) -> dict:
    """
    Assesses the completeness and freshness of market data.
    Returns score (0-100) and list of factors that affected it.

    A missing input costs a fixed deduction. An input that is present is then
    judged for freshness against its own source's limit (see _freshness).
    """
    score = 100.0
    factors = []
    positive = []
    grade = market_data.get("fuel_grade", "VLSFO")

    def judge(key: str, label: str):
        nonlocal score
        deduction, factor, good = _freshness(market_data, key, label, now)
        score -= deduction
        if factor:
            factors.append(factor)
        if good:
            positive.append(good)

    # EIA Brent spot
    if market_data.get("brent_available"):
        positive.append("EIA Brent spot price available.")
        judge("Brent spot", "EIA Brent spot")
    else:
        score -= 20.0
        factors.append("EIA Brent spot price unavailable. (−20)")

    # EIA forecast
    if market_data.get("forecast_available"):
        positive.append("EIA forward forecast available.")
        judge("Brent forecast", "EIA Brent forecast")
    else:
        score -= 10.0
        factors.append("EIA Brent forecast unavailable. (−10)")

    # Portwatch congestion
    if market_data.get("portwatch_available"):
        positive.append("IMF Portwatch congestion data available.")
        judge("Port congestion", "IMF PortWatch congestion data")
    else:
        score -= 15.0
        factors.append("IMF Portwatch congestion data unavailable. (−15)")

    # Bunker prices for the selected grade
    for port in ("Singapore", "Fujairah"):
        if market_data.get("bunker_prices", {}).get(port, {}).get("price"):
            positive.append(f"{port} {grade} price available.")
            judge(f"{port} {grade}", f"{port} {grade} price")
        else:
            score -= 15.0
            factors.append(f"{port} {grade} price unavailable — cost comparison is incomplete. (−15)")

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
    sg_price    = market_data.get("bunker_prices", {}).get("Singapore", {}).get("price")
    sg_prev     = market_data.get("bunker_prices", {}).get("Singapore", {}).get("price_prev")
    fuj_price   = market_data.get("bunker_prices", {}).get("Fujairah",  {}).get("price")
    fuj_prev    = market_data.get("bunker_prices", {}).get("Fujairah",  {}).get("price_prev")
    cong_sg     = market_data.get("congestion_signals", {}).get("Singapore", None)
    cong_fuj    = market_data.get("congestion_signals", {}).get("Fujairah", None)
    grade       = market_data.get("fuel_grade", "VLSFO")

    signals_available = 0
    signals_agree     = 0

    # Check crude vs Singapore bunker direction
    if brent_dir and sg_price and sg_prev:
        sg_dir = "Up" if sg_price > sg_prev else ("Down" if sg_price < sg_prev else "Flat")
        signals_available += 1
        if brent_dir == sg_dir:
            signals_agree += 1
            positive.append(f"Brent ({brent_dir}) and Singapore {grade} ({sg_dir}) moving in the same direction.")
        elif brent_dir != "Flat" and sg_dir != "Flat":
            score -= 15.0
            factors.append(f"Brent trending {brent_dir} but Singapore {grade} trending {sg_dir} — signal conflict. (−15)")

    # Check Singapore vs Fujairah direction
    if sg_price and sg_prev and fuj_price and fuj_prev:
        sg_dir  = "Up" if sg_price  > sg_prev  else ("Down" if sg_price  < sg_prev  else "Flat")
        fuj_dir = "Up" if fuj_price > fuj_prev else ("Down" if fuj_price < fuj_prev else "Flat")
        signals_available += 1
        if sg_dir == fuj_dir:
            signals_agree += 1
            positive.append(f"Singapore and Fujairah {grade} moving in the same direction ({sg_dir}).")
        elif sg_dir != "Flat" and fuj_dir != "Flat":
            score -= 10.0
            factors.append(f"Singapore {grade} ({sg_dir}) and Fujairah {grade} ({fuj_dir}) diverging. (−10)")

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

# Highest score that still reads as Medium (High starts at 80), and as Low
# (Medium starts at 60).
MEDIUM_CAP = 79.0
LOW_CAP = 59.0


def ports_missing_price(market_data: dict, ports: Iterable[str]) -> list:
    """Those of `ports` with no price for the selected fuel grade."""
    prices = market_data.get("bunker_prices", {})
    return [port for port in sorted(set(ports)) if not prices.get(port, {}).get("price")]


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
    now: Optional[datetime] = None,
) -> dict:
    """
    Combines the three components into a single Decision Confidence score.
    Returns full breakdown for display in the Decision Workspace.

    `scored_ports` are the ports of the options the engine scored. If any has
    Unknown congestion or no price, confidence is capped at Medium; if none has
    a price it is capped at Low. The reason is always shown.
    Required (no default) so a caller cannot silently skip the caps.
    `now` is for tests; it defaults to the current UTC time.
    """
    dq = compute_data_quality(market_data, now)
    sa = compute_signal_agreement(market_data)
    sc = compute_scenario_completeness(scenario)

    # Equal weighting for POC — can be refined
    combined = round(
        (dq["score"] * 0.40)
        + (sa["score"] * 0.30)
        + (sc["score"] * 0.30),
        1
    )
    uncapped = combined

    # Collect all confidence-reducing factors
    all_reductions = dq["factors"] + sa["factors"] + sc["factors"]

    # Caps. A cap is a ceiling, not a deduction: some gaps make a High (or even
    # Medium) label indefensible however good everything else is.
    scored_ports = sorted(set(scored_ports))
    cap_reasons = []

    # 1. Congestion unknown at any port the engine scored → at most Medium.
    unknown = unknown_congestion_ports(market_data, scored_ports)
    if unknown:
        detail = " ".join(unknown.values())
        cap_reasons.append(f"Congestion unknown at {', '.join(unknown)}: {detail} "
                           "Confidence is capped at Medium.")
        combined = min(combined, MEDIUM_CAP)

    # 2. Prices. Expected cost is the largest or second-largest weight in every
    #    risk profile. One scored port without a price means the cost comparison
    #    is one-sided → at most Medium. No scored port with a price means the
    #    cost criterion is blind and the ranking rests on congestion and
    #    schedule alone → at most Low.
    grade = market_data.get("fuel_grade", "VLSFO")
    unpriced = ports_missing_price(market_data, scored_ports)
    if scored_ports and len(unpriced) == len(scored_ports):
        cap_reasons.append(f"No {grade} price for any port being compared ({', '.join(unpriced)}): "
                           "the ranking cannot weigh cost. Confidence is capped at Low.")
        combined = min(combined, LOW_CAP)
    elif unpriced:
        cap_reasons.append(f"No {grade} price for {', '.join(unpriced)}: the cost comparison is "
                           "one-sided. Confidence is capped at Medium.")
        combined = min(combined, MEDIUM_CAP)

    cap_reason = " ".join(cap_reasons) or None
    if cap_reason:
        all_reductions = [cap_reason] + all_reductions

    return {
        "overall":               combined,
        "uncapped_overall":      uncapped,
        "cap_reason":            cap_reason,
        "cap_reasons":           cap_reasons,
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
