"""
tests/test_demo_mode.py

Demo mode must be deterministic: with demo data active, the Bunkering Strategy
engine uses fixed SAMPLE Brent, forecast and congestion values, so the README
demo scenarios give the same result whatever the live feeds say. The expected
values below are the README table — if a scenario result changes, update both.
"""

import unittest
from datetime import datetime, timezone

from modules.data import engine_inputs, load_data
from modules.decision.confidence_model import compute_confidence
from modules.decision.constraint_engine import run_constraint_engine
from modules.decision.evaluation_engine import score_options
from modules.decision.market_data import assemble_market_data
from modules.decision.options import generate_options
from modules.decision.scenario import BunkeringScenario, FuelAvailability, FuelGrade, RiskProfile
from modules.eia import EIA_SPOT
from modules.portwatch import PORTWATCH
from modules.provenance import SAMPLE_LABEL, stamp

# Mirrors the presets in app.py's "Load a demo scenario" expander, with the
# form's default values for everything the presets don't set.
SCENARIOS = {
    1: dict(fuel=900.0, sim_fuj_missing=False),
    2: dict(fuel=280.0, sim_fuj_missing=False),
    3: dict(fuel=900.0, sim_fuj_missing=True),
}

# README demo table: (confidence label, overall, top-ranked option, infeasible options)
EXPECTED = {
    1: ("High", 91.0, "Full bunker — Fujairah", {}),
    2: ("High", 91.0, "Full bunker — Singapore", {"Full bunker — Fujairah": "F1"}),
    3: ("High", 85.0, "Full bunker — Singapore", {}),
}


def _scenario(fuel: float) -> BunkeringScenario:
    return BunkeringScenario(
        vessel_name="MV Demo Trader", current_location="Colombo", destination="Rotterdam",
        fuel_remaining_mt=fuel, daily_consumption_mt=45.0, required_quantity_mt=1000.0,
        fuel_grade=list(FuelGrade)[0],
        eta_singapore_days=1.0, eta_fujairah_days=8.0, schedule_flexibility_hours=36.0,
        safety_reserve_mt=None,
        singapore_vlsfo_available=list(FuelAvailability)[2],
        fujairah_vlsfo_available=list(FuelAvailability)[2],
        risk_profile=list(RiskProfile)[1],
    )


def _run(n: int, live_eia, live_portwatch):
    """The Bunkering Strategy pipeline as app.py runs it, with demo data loaded."""
    df = load_data(source="sample")
    eia, portwatch = engine_inputs(df, live_eia, live_portwatch)
    scenario = _scenario(SCENARIOS[n]["fuel"])
    market_data = assemble_market_data(
        df, eia, portwatch, simulate_fujairah_missing=SCENARIOS[n]["sim_fuj_missing"])
    options = generate_options(scenario)
    options = run_constraint_engine(options, scenario, market_data["congestion_signals"])
    options = score_options(options, scenario, market_data)
    scored_ports = {p for o in options if o.is_feasible for p in (o.port, o.top_up_port) if p}
    return options, compute_confidence(scenario, market_data, scored_ports=scored_ports), market_data


def _summary(options, confidence):
    feasible = [o for o in options if o.is_feasible]
    top = max(feasible, key=lambda o: o.score).label
    infeasible = {o.label: o.infeasible_rule for o in options if not o.is_feasible}
    return confidence["label"], confidence["overall"], top, infeasible


# Live inputs that would change the result if demo mode let them through:
# rising Brent (cost-score nudge, conflict with falling demo VLSFO) and
# congestion that differs between the two ports.
_NOW = datetime.now(timezone.utc)
LIVE_EIA_RISING = {
    "spot": {"success": True, "current_value": 90.0, "previous_value": 85.0, "pct_change": 5.88,
             "direction": "Up", "latest_date": "2020-01-01",
             "provenance": stamp(EIA_SPOT, as_of=_NOW)},
    "forecast": {"success": False, "error": "test"},
}
LIVE_PORTWATCH_RISING = {
    "success": True, "ports": [], "source_name": "IMF Portwatch",
    "congestion_signals": {"Singapore": "Rising", "Fujairah": "Easing"},
    "provenance": stamp(PORTWATCH, as_of=_NOW),
}


class DemoScenariosMatchReadme(unittest.TestCase):
    def test_no_live_feeds(self):
        for n, expected in EXPECTED.items():
            with self.subTest(scenario=n):
                options, confidence, _ = _run(n, None, None)
                self.assertEqual(_summary(options, confidence), expected)

    def test_live_feeds_are_ignored_in_demo_mode(self):
        for n, expected in EXPECTED.items():
            with self.subTest(scenario=n):
                options, confidence, _ = _run(n, LIVE_EIA_RISING, LIVE_PORTWATCH_RISING)
                self.assertEqual(_summary(options, confidence), expected)

    def test_every_engine_input_is_labelled_sample(self):
        _, _, market_data = _run(1, LIVE_EIA_RISING, LIVE_PORTWATCH_RISING)
        for key in ("Brent spot", "Brent forecast", "Port congestion",
                    "Singapore VLSFO", "Fujairah VLSFO"):
            with self.subTest(input=key):
                prov = market_data["provenance"][key]
                self.assertEqual(prov.source_name, SAMPLE_LABEL)
                self.assertEqual(prov.licence, SAMPLE_LABEL)


class EngineInputsSelection(unittest.TestCase):
    def test_real_data_passes_live_inputs_through(self):
        df = load_data(source="none")
        self.assertEqual(engine_inputs(df, LIVE_EIA_RISING, LIVE_PORTWATCH_RISING),
                         (LIVE_EIA_RISING, LIVE_PORTWATCH_RISING))
        self.assertEqual(engine_inputs(df, None, None), (None, None))


if __name__ == "__main__":
    unittest.main()
