"""
tests/test_portwatch_congestion.py

Missing or unusable PortWatch data must give "Unknown" with a reason, never
"Stable". Rows are invented test values. No network: requests.get is patched.
"""

import unittest
from unittest import mock

from modules import portwatch
from modules.portwatch import _compute_congestion

PORTS = ["Singapore", "Fujairah"]


def row(port, day, calls):
    return {"portname": port, "date": day, "portcalls": calls}


class ComputeCongestionTests(unittest.TestCase):
    def test_port_with_no_rows_is_unknown_with_reason(self):
        signals, reasons = _compute_congestion([row("Singapore", "2026-10-02", 100),
                                                row("Singapore", "2026-09-25", 100)], PORTS)
        self.assertEqual(signals["Fujairah"], "Unknown")
        self.assertIn("No PortWatch rows for Fujairah", reasons["Fujairah"])
        self.assertNotIn("Singapore", reasons)

    def test_one_day_of_data_is_unknown_with_reason(self):
        signals, reasons = _compute_congestion([row("Fujairah", "2026-10-02", 7)], ["Fujairah"])
        self.assertEqual(signals["Fujairah"], "Unknown")
        self.assertIn("Only 1 day", reasons["Fujairah"])

    def test_null_call_counts_do_not_count_as_days(self):
        signals, _ = _compute_congestion([row("Fujairah", "2026-10-02", 7),
                                          row("Fujairah", "2026-10-01", None)], ["Fujairah"])
        self.assertEqual(signals["Fujairah"], "Unknown")

    def test_zero_calls_on_earliest_day_is_unknown_with_reason(self):
        signals, reasons = _compute_congestion([row("Fujairah", "2026-10-02", 7),
                                                row("Fujairah", "2026-09-20", 0)], ["Fujairah"])
        self.assertEqual(signals["Fujairah"], "Unknown")
        self.assertIn("zero port calls", reasons["Fujairah"])
        self.assertIn("20 September 2026", reasons["Fujairah"])

    def test_usable_data_still_gives_a_direction(self):
        signals, reasons = _compute_congestion([row("Singapore", "2026-10-02", 120),
                                                row("Singapore", "2026-09-20", 100)], ["Singapore"])
        self.assertEqual(signals["Singapore"], "Rising")
        self.assertEqual(reasons, {})

    def test_epoch_millisecond_dates_sort_correctly(self):
        # 20-09-2026 (100 calls) then 02-10-2026 (80 calls) as epoch ms, oldest first in the input.
        signals, _ = _compute_congestion([row("Singapore", 1789862400000, 100),
                                          row("Singapore", 1790899200000, 80)], ["Singapore"])
        self.assertEqual(signals["Singapore"], "Easing")

    def test_every_unknown_has_a_reason(self):
        signals, reasons = _compute_congestion([row("Fujairah", "2026-10-02", 7)], PORTS)
        for port, signal in signals.items():
            if signal == "Unknown":
                self.assertTrue(reasons.get(port), port)


class FetchPortActivityTests(unittest.TestCase):
    def test_every_target_port_is_reported(self):
        features = [{"attributes": row("Singapore", d, 100)} for d in ("2026-10-02", "2026-09-25")]
        response = mock.Mock(**{"json.return_value": {"features": features}, "raise_for_status.return_value": None})
        with mock.patch.object(portwatch.requests, "get", return_value=response):
            result = portwatch.fetch_port_activity()
        self.assertEqual(set(result["congestion_signals"]), set(portwatch.TARGET_PORTS))
        self.assertEqual(result["congestion_signals"]["Singapore"], "Stable")
        self.assertEqual(set(result["congestion_reasons"]), set(portwatch.TARGET_PORTS) - {"Singapore"})


class HoustonNameTests(unittest.TestCase):
    def _fetch(self, features):
        response = mock.Mock(**{"json.return_value": {"features": features}, "raise_for_status.return_value": None})
        with mock.patch.object(portwatch.requests, "get", return_value=response) as get:
            return portwatch.fetch_port_activity(), get.call_args.kwargs["params"]["where"]

    def test_query_uses_portwatch_name_for_houston(self):
        _, where = self._fetch([])
        self.assertIn("'Houston (US-TX)'", where)
        self.assertNotIn("'Houston'", where)
        self.assertIn("'Singapore'", where)

    def test_houston_rows_come_back_under_the_app_name(self):
        features = [{"attributes": row("Houston (US-TX)", d, n)} for d, n in (("2026-10-02", 24), ("2026-09-20", 20))]
        result, _ = self._fetch(features)
        self.assertEqual(result["congestion_signals"]["Houston"], "Rising")
        self.assertNotIn("Houston (US-TX)", result["congestion_signals"])
        self.assertEqual({r["portname"] for r in result["ports"]}, {"Houston"})

    def test_mapping_is_the_only_rename(self):
        self.assertEqual(portwatch.PORTWATCH_NAMES, {"Houston": "Houston (US-TX)"})


if __name__ == "__main__":
    unittest.main()
