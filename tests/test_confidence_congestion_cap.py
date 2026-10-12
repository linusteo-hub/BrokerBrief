"""
tests/test_confidence_congestion_cap.py

If any port the engine scored has Unknown congestion, confidence is capped at
Medium and the output says why. Uses the demo pipeline (fixed SAMPLE inputs,
which give High) and then knocks out one port's congestion.
"""

import unittest

from modules.data import engine_inputs, load_data
from modules.decision.confidence_model import MEDIUM_CAP, compute_confidence
from modules.decision.market_data import assemble_market_data
from modules.decision.scenario import BunkeringScenario, FuelAvailability, FuelGrade, RiskProfile


def demo_market():
    df = load_data(source="sample")
    eia, portwatch = engine_inputs(df, None, None)
    return assemble_market_data(df, eia, portwatch, simulate_fujairah_missing=False)


SCENARIO = BunkeringScenario(
    vessel_name="MV Demo Trader", current_location="Colombo", destination="Rotterdam",
    fuel_remaining_mt=900.0, daily_consumption_mt=45.0, required_quantity_mt=1000.0,
    fuel_grade=list(FuelGrade)[0], eta_singapore_days=1.0, eta_fujairah_days=8.0,
    schedule_flexibility_hours=36.0, safety_reserve_mt=None,
    singapore_vlsfo_available=list(FuelAvailability)[2],
    fujairah_vlsfo_available=list(FuelAvailability)[2],
    risk_profile=list(RiskProfile)[1],
)
BOTH = {"Singapore", "Fujairah"}


class CongestionCapTests(unittest.TestCase):
    def test_known_congestion_is_not_capped(self):
        conf = compute_confidence(SCENARIO, demo_market(), scored_ports=BOTH)
        self.assertEqual(conf["label"], "High")
        self.assertIsNone(conf["cap_reason"])

    def test_unknown_scored_port_caps_high_to_medium_with_reason(self):
        market = demo_market()
        market["congestion_signals"]["Fujairah"] = "Unknown"
        market["congestion_reasons"] = {"Fujairah": "Only 1 day of PortWatch data for Fujairah."}
        conf = compute_confidence(SCENARIO, market, scored_ports=BOTH)
        self.assertGreaterEqual(conf["uncapped_overall"], 80)       # would have been High
        self.assertEqual((conf["label"], conf["overall"]), ("Medium", MEDIUM_CAP))
        self.assertIn("Congestion unknown at Fujairah", conf["cap_reason"])
        self.assertIn("Only 1 day of PortWatch data", conf["cap_reason"])
        self.assertEqual(conf["reductions"][0], conf["cap_reason"])

    def test_missing_signal_counts_as_unknown(self):
        market = demo_market()
        del market["congestion_signals"]["Singapore"]
        conf = compute_confidence(SCENARIO, market, scored_ports=BOTH)
        self.assertEqual(conf["label"], "Medium")
        self.assertIn("No PortWatch congestion signal for Singapore.", conf["cap_reason"])

    def test_unknown_port_that_was_not_scored_does_not_cap(self):
        market = demo_market()
        market["congestion_signals"]["Houston"] = "Unknown"
        conf = compute_confidence(SCENARIO, market, scored_ports=BOTH)
        self.assertEqual(conf["label"], "High")

    def test_cap_never_raises_a_lower_score(self):
        market = demo_market()
        market["congestion_signals"]["Fujairah"] = "Unknown"
        market["brent_available"] = False          # pushes the score down
        market["forecast_available"] = False
        conf = compute_confidence(SCENARIO, market, scored_ports=BOTH)
        self.assertLessEqual(conf["overall"], conf["uncapped_overall"])
        self.assertIsNotNone(conf["cap_reason"])

    def test_scored_ports_is_required(self):
        with self.assertRaises(TypeError):
            compute_confidence(SCENARIO, demo_market())


if __name__ == "__main__":
    unittest.main()
