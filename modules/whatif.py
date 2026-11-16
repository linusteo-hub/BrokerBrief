"""
modules/whatif.py

What-if support for the Bunkering Strategy page. It runs the existing decision
engine (it never changes it) over a range of inputs, to show where each option
starts or stops being feasible.

Why scan rather than solve: feasibility comes from several rules at once (F1
reserve, F2/C1 stem limits, S1 schedule), and the partial option's quantity
itself depends on fuel on board. A closed-form answer would duplicate the
engine's logic and drift from it; a scan asks the engine itself. The cost is a
few hundred cheap engine calls, which the app caches per scenario.
"""

from dataclasses import replace
from typing import Dict, List, Optional

from modules.decision.options import generate_options
from modules.decision.constraint_engine import run_constraint_engine
from modules.decision.evaluation_engine import score_options
from modules.decision.scenario import BunkeringScenario


def run_pipeline(scenario: BunkeringScenario, market_data: dict) -> list:
    """Options -> Constraint Engine -> Commercial Evaluation, exactly as the app runs it."""
    options = generate_options(scenario)
    options = run_constraint_engine(options, scenario, market_data["congestion_signals"])
    return score_options(options, scenario, market_data)


def _feasible_ids(scenario: BunkeringScenario, congestion: dict) -> set:
    return {o.id for o in run_constraint_engine(generate_options(scenario), scenario, congestion) if o.is_feasible}


def fuel_thresholds(scenario: BunkeringScenario, congestion: dict,
                    step: float = 5.0, ceiling: Optional[float] = None) -> Dict[str, Optional[float]]:
    """Lowest fuel on board (MT, to the nearest `step`) at which each option is feasible.

    None means the option is not feasible anywhere in the scanned range, i.e. something
    other than fuel (grade, ECA, stem limits, schedule) rules it out.
    """
    ceiling = ceiling or max(3000.0, scenario.fuel_remaining_mt * 2)
    first: Dict[str, Optional[float]] = {}
    fuel = 0.0
    while fuel <= ceiling:
        for oid in _feasible_ids(replace(scenario, fuel_remaining_mt=fuel), congestion):
            first.setdefault(oid, fuel)
        fuel += step
    return {o.id: first.get(o.id) for o in generate_options(scenario)}


def eta_limits(scenario: BunkeringScenario, congestion: dict, port: str = "Fujairah",
               step: float = 0.1, ceiling: float = 20.0) -> Dict[str, Optional[float]]:
    """Longest ETA to `port` (days) at which each option that calls there is still feasible.

    None means the option is not feasible even at the shortest ETA scanned.
    """
    field = "eta_fujairah_days" if port == "Fujairah" else "eta_singapore_days"
    last: Dict[str, float] = {}
    eta = step
    while eta <= ceiling + 1e-9:
        for oid in _feasible_ids(replace(scenario, **{field: round(eta, 2)}), congestion):
            last[oid] = round(eta, 2)
        eta += step
    calls_port = [o.id for o in generate_options(scenario) if port in (o.port, o.top_up_port)]
    return {oid: last.get(oid) for oid in calls_port}


def threshold_sentences(scenario: BunkeringScenario, congestion: dict, labels: Dict[str, str]) -> List[str]:
    """Plain-English lines for the What-if tab, one per option where a threshold exists."""
    lines = []
    fuel = fuel_thresholds(scenario, congestion)
    have = scenario.fuel_remaining_mt
    for oid, mt in fuel.items():
        name = labels.get(oid, oid)
        if mt is None:
            lines.append(f"{name}: not feasible at any fuel level up to the scanned limit; another rule removes it.")
        elif mt > have:
            lines.append(f"{name}: needs at least {mt:,.0f} MT on board (you have {have:,.0f} MT).")
        else:
            lines.append(f"{name}: feasible from {mt:,.0f} MT on board (you have {have:,.0f} MT).")
    ceiling = 20.0
    for oid, days in eta_limits(scenario, congestion, ceiling=ceiling).items():
        name = labels.get(oid, oid)
        if days is None:
            continue
        if days >= ceiling:
            lines.append(f"{name}: feasible at every ETA to Fujairah tested (up to {ceiling:.0f} days).")
        else:
            lines.append(f"{name}: works with up to {days:.1f} days to Fujairah (you entered {scenario.eta_fujairah_days:.1f}).")
    return lines
