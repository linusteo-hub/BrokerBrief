"""
tests/test_congestion_unknown_engine.py

A port with no congestion signal, or an "Unknown" one, must reach the
"Congestion data unavailable — moderate risk assumed" branch (55), never be
scored as Stable (70), and say why.
"""

import unittest

from modules.decision.constraint_engine import run_constraint_engine
from modules.decision.evaluation_engine import _score_operational_risk, _score_schedule_risk
from modules.decision.options import generate_options
from modules.decision.scenario import BunkeringScenario, FuelAvailability, FuelGrade, RiskProfile


def scenario(flex=36.0):
    return BunkeringScenario(
        vessel_name="MV Test", current_location="Colombo", destination="Rotterdam",
        fuel_remaining_mt=900.0, daily_consumption_mt=45.0, required_quantity_mt=1000.0,
        fuel_grade=list(FuelGrade)[0], eta_singapore_days=1.0, eta_fujairah_days=8.0,
        schedule_flexibility_hours=flex, safety_reserve_mt=None,
        singapore_vlsfo_available=list(FuelAvailability)[2],
        fujairah_vlsfo_available=list(FuelAvailability)[2],
        risk_profile=list(RiskProfile)[1],
    )


def full_bunker_at(port):
    return next(o for o in generate_options(scenario()) if o.port == port and not o.is_partial
                and o.top_up_port is None and "Full" in o.label)


class UnknownCongestionTests(unittest.TestCase):
    def test_missing_port_scores_55_not_stable_70(self):
        option = full_bunker_at("Fujairah")
        score, note = _score_operational_risk(option, {"congestion_signals": {"Singapore": "Stable"}})
        self.assertEqual(score, 55.0)
        self.assertIn("Congestion data unavailable for Fujairah — moderate risk assumed.", note)
        self.assertIn("No PortWatch congestion signal for Fujairah.", note)

    def test_unknown_signal_scores_55_and_carries_its_reason(self):
        option = full_bunker_at("Fujairah")
        market = {"congestion_signals": {"Fujairah": "Unknown"},
                  "congestion_reasons": {"Fujairah": "Only 1 day of PortWatch data for Fujairah."}}
        score, note = _score_operational_risk(option, market)
        self.assertEqual(score, 55.0)
        self.assertIn("Only 1 day of PortWatch data for Fujairah.", note)

    def test_stable_is_still_70(self):
        score, _ = _score_operational_risk(full_bunker_at("Fujairah"), {"congestion_signals": {"Fujairah": "Stable"}})
        self.assertEqual(score, 70.0)

    def test_schedule_risk_names_the_assumption(self):
        _, note = _score_schedule_risk(full_bunker_at("Fujairah"), scenario(), {"congestion_signals": {}})
        self.assertIn("Congestion at Fujairah is unknown", note)

    def test_schedule_check_names_the_assumption(self):
        # Flexibility below wait + bunkering time triggers the schedule warning.
        options = run_constraint_engine(generate_options(scenario(flex=6.0)), scenario(flex=6.0), {})
        warnings = " ".join(o.warning_message or "" for o in options)
        self.assertIn("is unknown, so a moderate 8h wait is assumed", warnings)
        self.assertNotIn("congestion signal (Stable)", warnings)


if __name__ == "__main__":
    unittest.main()
