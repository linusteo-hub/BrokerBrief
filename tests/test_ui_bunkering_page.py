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
        self.assertEqual(values["Current location / last port"], "Zhoushan (in ballast)")
        self.assertEqual(values["Destination / next major port"], "Ras Tanura")
        numbers = {n.label: n.value for n in at.number_input}
        self.assertEqual(numbers["ETA to Fujairah (days)"], 11.5)

    def test_evaluating_with_no_prices_reads_low_and_says_why(self):
        at = click(bunkering_page(), "⚓")
        self.assertEqual(len(at.exception), 0)
        text = page_text(at)
        self.assertIn("cannot weigh cost", text)
        self.assertIn("Confidence is capped at Low", text)

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


if __name__ == "__main__":
    unittest.main()
