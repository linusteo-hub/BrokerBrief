"""
modules/decision/constraint_engine.py

Constraint Engine — Layer 1 of the BrokerBrief decision pipeline.

Golden rule: Only contains constraints that are objectively true and
independent of commercial strategy.

Layer 1 answers: "Can this option reasonably exist?"
Layer 2 answers: "Which feasible option is commercially strongest?"

All rules are deterministic. Options violating a rule are marked INFEASIBLE
with the specific rule and reason stated. Users always see WHY an option
was removed.
"""

from typing import List, Tuple
from modules.decision.scenario import BunkeringScenario, FuelAvailability
from modules.decision.options import BunkeringOption

# ── Port data (POC defaults — replace with database later) ──────────────────
# Minimum stem sizes in MT. Source: indicative industry values.
# If unknown, we flag the gap rather than invent a number.
PORT_MIN_STEM_MT = {
    "Singapore": 200.0,
    "Fujairah":  200.0,
}

PORT_MAX_STEM_MT = {
    "Singapore": 10_000.0,
    "Fujairah":  10_000.0,
}

# Estimated bunkering time in hours (ship alongside + operations)
PORT_BUNKERING_TIME_HOURS = {
    "Singapore": 8.0,
    "Fujairah":  10.0,
}

# ECA zone membership (True = MARPOL Annex VI ECA applies)
PORT_IN_ECA = {
    "Singapore": False,
    "Fujairah":  False,
    "Rotterdam": True,
    "Houston":   True,
}

# ── Congestion → estimated waiting time mapping ──────────────────────────────
# Source: indicative thresholds, to be validated with industry data.
# These are estimates — labelled as such in the workspace.
CONGESTION_WAIT_HOURS = {
    "Rising":  18.0,   # High congestion → 18h estimate
    "Stable":  8.0,    # Normal operations → 8h estimate
    "Easing":  4.0,    # Improving → 4h estimate
}


def _fuel_safety_check(
    option: BunkeringOption,
    scenario: BunkeringScenario,
) -> Tuple[bool, str, str]:
    """
    F1: Can vessel physically reach this bunkering port while maintaining
    the required safety reserve?
    Returns (is_feasible, rule_id, reason).
    """
    if option.port == "Singapore":
        fuel_needed = scenario.fuel_to_reach_singapore_mt()
    elif option.port == "Fujairah":
        fuel_needed = scenario.fuel_to_reach_fujairah_mt()
    else:
        fuel_needed = 0.0

    reserve = scenario.effective_safety_reserve_mt()
    required_total = fuel_needed + reserve

    if scenario.fuel_remaining_mt < required_total:
        shortfall = required_total - scenario.fuel_remaining_mt
        return (
            False,
            "F1",
            (
                f"Vessel requires {required_total:,.1f} MT to reach {option.port} "
                f"while maintaining the safety reserve ({reserve:,.1f} MT). "
                f"Current fuel remaining: {scenario.fuel_remaining_mt:,.1f} MT. "
                f"Shortfall: {shortfall:,.1f} MT."
            ),
        )
    return True, "", ""


def _min_stem_check(
    option: BunkeringOption,
    scenario: BunkeringScenario,
) -> Tuple[bool, str, str]:
    """
    F2: Is the requested quantity above the minimum stem size?
    If minimum stem data is unknown, flag the gap but do not remove the option.
    """
    port = option.port
    min_stem = PORT_MIN_STEM_MT.get(port)
    if min_stem is None:
        # Data gap — do not invent a number, do not remove option
        return True, "", ""
    if option.quantity_mt < min_stem:
        return (
            False,
            "F2",
            (
                f"Requested quantity ({option.quantity_mt:,.0f} MT) is below the "
                f"minimum stem size at {port} ({min_stem:,.0f} MT)."
            ),
        )
    return True, "", ""


def _max_stem_check(
    option: BunkeringOption,
    scenario: BunkeringScenario,
) -> Tuple[bool, str, str]:
    """
    C1: Does the requested quantity exceed the maximum stem available?
    """
    port = option.port
    max_stem = PORT_MAX_STEM_MT.get(port)
    if max_stem is None:
        return True, "", ""
    if option.quantity_mt > max_stem:
        return (
            False,
            "C1",
            (
                f"Requested quantity ({option.quantity_mt:,.0f} MT) exceeds the "
                f"maximum available single stem at {port} ({max_stem:,.0f} MT)."
            ),
        )
    return True, "", ""


def _fuel_grade_check(
    option: BunkeringOption,
    scenario: BunkeringScenario,
) -> Tuple[bool, str, str]:
    """
    P1: Is the required fuel grade available at this port?
    UNKNOWN → option retained, confidence reduced in Confidence Model.
    UNAVAILABLE → option INFEASIBLE.
    """
    port = option.port
    if port == "Singapore":
        availability = scenario.singapore_vlsfo_available
    elif port == "Fujairah":
        availability = scenario.fujairah_vlsfo_available
    else:
        availability = FuelAvailability.UNKNOWN

    if availability == FuelAvailability.UNAVAILABLE:
        return (
            False,
            "P1",
            (
                f"Required fuel grade ({scenario.fuel_grade.value}) is explicitly "
                f"unavailable at {port}. Option removed."
            ),
        )
    return True, "", ""


def _eca_check(
    option: BunkeringOption,
    scenario: BunkeringScenario,
) -> Tuple[bool, str, str]:
    """
    R1: HSFO is not permitted in ECA zones.
    """
    port = option.port
    in_eca = PORT_IN_ECA.get(port, False)
    if scenario.fuel_grade.value == "HSFO" and in_eca:
        return (
            False,
            "R1",
            (
                f"HSFO is not permitted in {port} (ECA zone — MARPOL Annex VI). "
                "This option is legally infeasible."
            ),
        )
    return True, "", ""


def _schedule_check(
    option: BunkeringOption,
    scenario: BunkeringScenario,
    congestion_signals: dict,
) -> Tuple[bool, str, str, bool, str]:
    """
    S1/S2: Does the total time required for this bunkering option exceed
    the vessel's schedule flexibility?

    Returns (is_feasible, rule_id, reason, is_warning, warning_msg).
    """
    port = option.port
    congestion = congestion_signals.get(port, "Stable")
    est_wait_hours = CONGESTION_WAIT_HOURS.get(congestion, 8.0)
    bunkering_time = PORT_BUNKERING_TIME_HOURS.get(port, 8.0)

    # Sailing time already included in ETA
    total_port_time_hours = est_wait_hours + bunkering_time

    if total_port_time_hours > scenario.schedule_flexibility_hours:
        if scenario.schedule_flexibility_hours == 0:
            # Hard infeasibility only if zero flexibility
            return (
                False, "S1",
                (
                    f"Estimated total port time at {port} is "
                    f"{total_port_time_hours:.0f} hours "
                    f"(waiting: {est_wait_hours:.0f}h estimated + "
                    f"bunkering: {bunkering_time:.0f}h). "
                    f"Vessel has zero schedule flexibility."
                ),
                False, "",
            )
        else:
            # Schedule is tight but not zero — issue warning, not removal
            return (
                True, "", "",
                True,
                (
                    f"Schedule tight at {port}. Estimated port time "
                    f"({total_port_time_hours:.0f}h) exceeds flexibility "
                    f"({scenario.schedule_flexibility_hours:.0f}h). "
                    f"Waiting time is estimated from congestion signal ({congestion})."
                ),
            )

    return True, "", "", False, ""


def _departure_reserve_warning(
    option: BunkeringOption,
    scenario: BunkeringScenario,
) -> Tuple[bool, str]:
    """
    F3: Would the vessel depart below safety reserve after this bunkering?
    WARNING only — not a hard removal. Professional may have valid reason.
    """
    fuel_after = (
        scenario.fuel_remaining_mt
        - (scenario.fuel_to_reach_singapore_mt() if option.port == "Singapore"
           else scenario.fuel_to_reach_fujairah_mt())
        + option.quantity_mt
    )
    reserve = scenario.effective_safety_reserve_mt()
    if fuel_after < reserve:
        return (
            True,
            (
                f"Post-bunkering fuel ({fuel_after:,.1f} MT) would be below "
                f"safety reserve ({reserve:,.1f} MT) after departure. "
                "Review before proceeding."
            ),
        )
    return False, ""


# ── Main Constraint Engine ────────────────────────────────────────────────────
def run_constraint_engine(
    options: List[BunkeringOption],
    scenario: BunkeringScenario,
    congestion_signals: dict,
) -> List[BunkeringOption]:
    """
    Applies all Layer 1 feasibility rules to each option.
    Marks infeasible options with rule ID and reason.
    Issues warnings where appropriate without removing options.
    Returns the full list (both feasible and infeasible) for display.
    """
    for option in options:
        reasons = []
        warnings = []

        # ── Hard feasibility checks ──────────────────────────────────────────
        checks = [
            _fuel_safety_check(option, scenario),
            _min_stem_check(option, scenario),
            _max_stem_check(option, scenario),
            _fuel_grade_check(option, scenario),
            _eca_check(option, scenario),
        ]

        for feasible, rule_id, reason in checks:
            if not feasible:
                option.is_feasible = False
                option.infeasible_rule   = rule_id
                option.infeasible_reason = reason
                break  # First violated rule removes the option

        # ── Schedule check (can produce warning or infeasibility) ─────────────
        if option.is_feasible:
            feasible, rule_id, reason, is_warn, warn_msg = _schedule_check(
                option, scenario, congestion_signals
            )
            if not feasible:
                option.is_feasible = False
                option.infeasible_rule   = rule_id
                option.infeasible_reason = reason
            elif is_warn:
                option.is_warning = True
                warnings.append(warn_msg)

        # ── F3 departure reserve warning ──────────────────────────────────────
        if option.is_feasible:
            is_warn, warn_msg = _departure_reserve_warning(option, scenario)
            if is_warn:
                option.is_warning = True
                warnings.append(warn_msg)

        if warnings:
            option.warning_message = " | ".join(warnings)

    return options
