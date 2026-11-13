"""
tests/test_ui_bunkering_page.py

Runs the Bunkering Strategy page in Streamlit's test harness (no network:
PortWatch is patched, no EIA key is configured) and checks what a visitor sees.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from modules import portwatch
from modules.provenance import stamp

APP = str(Path(__file__).resolve().parent.parent / "app.py")
FAKE = {
    "success": True, "ports": [], "source_name": "IMF Portwatch", "source_url": "https://portwatch.imf.org",
    "congestion_signals": {"Singapore": "Stable", "Fujairah": "Stable"},
    "congestion_reasons": {},
    "provenance": stamp(portwatch.PORTWATCH, as_of=datetime.now(timezone.utc)),
}


def bunkering_page():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.session_state["portwatch_data"] = None
    radio = at.sidebar.radio[0]
    radio.set_value(next(o for o in radio.options if "Bunkering" in o)).run()
    return at


def click(at, label_start):
    next(b for b in at.button if b.label.startswith(label_start)).click().run()
    return at


def page_text(at):
    return " ".join(str(m.value) for m in list(at.markdown) + list(at.caption) + list(at.warning)
                    + list(at.error) + list(at.info) + list(at.success))


class BunkeringPage(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults_are_the_documented_voyage(self):
        at = bunkering_page()
        self.assertEqual(len(at.exception), 0)
        values = {t.label: t.value for t in at.text_input}
        self.assertEqual(values["Current location / last port"], "South China Sea, ex Zhoushan (in ballast)")
        self.assertEqual(values["Destination / next major port"], "Ras Tanura")
        numbers = {n.label: n.value for n in at.number_input}
        self.assertEqual(numbers["ETA to Singapore (days)"], 1.0)
        self.assertEqual(numbers["ETA to Fujairah (days)"], 11.5)
        self.assertEqual(numbers["Daily consumption (MT/day)"], 45.0)

    def test_evaluating_with_no_prices_reads_low_and_says_why(self):
        at = click(bunkering_page(), "⚓")
        self.assertEqual(len(at.exception), 0)
        text = page_text(at)
        self.assertIn("cannot weigh cost", text)
        self.assertIn("59% <span", text)                      # headline
        self.assertIn("(Low)", text)
        self.assertIn("⚠ Capped at Low (would be", text)       # the strip names the level it capped at
        self.assertNotIn("Capped at Medium", text)

    def test_one_typed_price_caps_at_medium_only_if_the_cap_bites(self):
        at = bunkering_page()
        next(n for n in at.number_input if n.label == "Singapore VLSFO price (USD/MT)").set_value(600.0).run()
        at = click(at, "⚓")
        text = page_text(at)
        self.assertIn("No VLSFO price for Fujairah", text)
        self.assertNotIn("Capped at Low", text)
        # The score is already below 80 here, so the strip must not claim it was lowered.
        self.assertIn("A cap applies, but the score was already below it.", text)

    def test_a_price_typed_for_one_grade_is_not_used_for_another(self):
        at = bunkering_page()
        next(n for n in at.number_input if n.label == "Singapore VLSFO price (USD/MT)").set_value(600.0).run()
        next(n for n in at.number_input if n.label == "Fujairah VLSFO price (USD/MT)").set_value(590.0).run()
        next(s for s in at.selectbox if s.label == "Required fuel grade").set_value("MGO").run()
        labels = {n.label: n.value for n in at.number_input}
        self.assertEqual(labels["Singapore MGO price (USD/MT)"], 0.0)
        at = click(at, "⚓")
        text = page_text(at)
        self.assertIn("No MGO price for any port", text)
        self.assertNotIn("$600", text)

    def test_data_sources_show_source_date_and_licence(self):
        at = click(click(bunkering_page(), "Scenario 1"), "⚓")
        text = page_text(at)
        self.assertIn("licence: SAMPLE — not real data", text)
        self.assertRegex(text, r"as of \d{2}-\d{2}-\d{4}")

    def test_demo_scenario_three_reads_medium(self):
        at = click(bunkering_page(), "Scenario 3")
        at = click(at, "⚓")
        self.assertEqual(len(at.exception), 0)
        text = page_text(at)
        self.assertIn("No VLSFO price for Fujairah", text)
        self.assertIn("DEMO DATA ACTIVE", text)

    def test_hsfo_without_scrubber_shows_r1_for_every_option(self):
        at = bunkering_page()
        next(s for s in at.selectbox if s.label == "Required fuel grade").set_value("HSFO").run()
        at = click(at, "⚓")
        self.assertEqual(len(at.exception), 0)
        text = page_text(at)
        self.assertIn("regulation 14.1", text)
        self.assertNotIn("is not permitted in", text)


class LiveFetchCaching(unittest.TestCase):
    """app.py's shared cache: successes are kept, failures are retried only
    after a short hold, and the server-side key never reaches a widget."""

    def test_a_failing_feed_is_not_refetched_on_every_rerun(self):
        failing = mock.Mock(return_value={"success": False, "error": "boom", "ports": [], "congestion_signals": {}})
        with mock.patch.object(portwatch, "fetch_port_activity", failing):
            at = AppTest.from_file(APP, default_timeout=60).run()
            for _ in range(3):
                at.run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(failing.call_count, 1)

    def test_a_successful_fetch_is_shared_across_reruns(self):
        ok = mock.Mock(return_value=FAKE)
        with mock.patch.object(portwatch, "fetch_port_activity", ok):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.run()
            at.run()
        self.assertEqual(ok.call_count, 1)

    def test_server_key_is_never_put_in_a_widget_or_session_state(self):
        from modules import eia
        secret = "SERVERSECRET123"
        fake_eia = {"spot": {"success": False, "error": "x"}, "forecast": {"success": False, "error": "x"}}
        with mock.patch.dict("os.environ", {"EIA_API_KEY": secret}), \
             mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE), \
             mock.patch.object(eia, "fetch_all", return_value=fake_eia) as fetch_all:
            at = AppTest.from_file(APP, default_timeout=60).run()
        self.assertEqual(len(at.exception), 0)
        fetch_all.assert_called_once_with(secret)
        self.assertEqual([t.label for t in at.sidebar.text_input], [])        # no key box
        self.assertFalse(any(b.label.startswith("↺") for b in at.sidebar.button))
        self.assertNotEqual(at.session_state["eia_key"], secret)
        self.assertNotIn(secret, page_text(at))


class MarketIntelligencePage(unittest.TestCase):
    def test_signal_table_renders_with_real_rows(self):
        import pandas as pd
        from modules.data import REQUIRED_COLUMNS
        rows = [{"date": "2026-11-12", "signal_type": kind, "market_segment": seg, "route_or_port": place,
                 "current_value": cur, "previous_value": prev, "unit": unit, "source_name": "My broker notes",
                 # The signal engine ignores rows without a source URL ("no source, no certainty").
                 "source_url": "https://example.org/notes", "updated_at": "2026-11-12", "confidence": 0.9, "notes": ""}
                for kind, seg, place, cur, prev, unit in (
                    ("bunker", "VLSFO", "Singapore", 610, 600, "USD/MT"),
                    ("bunker", "VLSFO", "Fujairah", 600, 605, "USD/MT"),
                    ("freight", "Tanker", "Route A", 30000, 28000, "USD/day"))]
        with mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.session_state["df"] = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
            at.session_state["data_source"] = "csv"
            radio = at.sidebar.radio[0]
            radio.set_value(next(o for o in radio.options if "Market Intelligence" in o)).run()
        self.assertEqual(len(at.exception), 0)
        self.assertGreaterEqual(len(at.dataframe), 1)


if __name__ == "__main__":
    unittest.main()
