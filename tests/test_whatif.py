"""
tests/test_whatif.py

The what-if thresholds must agree with the engine itself. Hand-checked figures
use the README demo scenario: 45 MT/day, ETA Fujairah 8 days, default reserve
= max(10% of fuel on board, 24h consumption).
"""

import unittest

from modules.data import engine_inputs, load_data
from modules.decision.market_data import assemble_market_data
from modules.whatif import eta_limits, fuel_thresholds, run_pipeline, threshold_sentences
from tests.test_demo_mode import _run, _scenario


def _market(sim_fuj_missing=False):
    df = load_data(source="sample")
    eia, portwatch = engine_inputs(df, None, None)
    return assemble_market_data(df, eia, portwatch, simulate_fujairah_missing=sim_fuj_missing)


class WhatIfTests(unittest.TestCase):
    def test_pipeline_matches_the_app_pipeline(self):
        options, _, market = _run(2, None, None)
        mine = run_pipeline(_scenario(280.0), market)
        self.assertEqual([(o.id, o.is_feasible, o.score) for o in options],
                         [(o.id, o.is_feasible, o.score) for o in mine])

    def test_fujairah_fuel_threshold_is_405_mt(self):
        # 8 days x 45 MT/day + 45 MT reserve (24h consumption beats 10% of 405 MT) = 405 MT.
        market = _market()
        thresholds = fuel_thresholds(_scenario(280.0), market["congestion_signals"])
        self.assertEqual(thresholds["FUJ_FULL"], 405.0)
        self.assertLessEqual(thresholds["SGP_FULL"], 280.0)

    def test_fujairah_eta_limit_is_18_days_at_900_mt(self):
        # 900 MT on board, reserve 90 MT: 45 x ETA + 90 <= 900  ->  ETA <= 18 days.
        market = _market()
        self.assertEqual(eta_limits(_scenario(900.0), market["congestion_signals"])["FUJ_FULL"], 18.0)

    def test_sentences_say_how_far_short_the_vessel_is(self):
        market = _market()
        lines = threshold_sentences(_scenario(280.0), market["congestion_signals"],
                                    {"FUJ_FULL": "Full bunker — Fujairah"})
        self.assertIn("Full bunker — Fujairah: needs at least 405 MT on board (you have 280 MT).", lines)


if __name__ == "__main__":
    unittest.main()
