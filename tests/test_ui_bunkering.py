"""
tests/test_ui_bunkering.py

The Bunkering strategy page in Streamlit's test harness (PortWatch patched, no
network). Checks the live results, that step inputs survive moving between
steps, and the breakdown and compare interactions.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from modules import portwatch
from modules.provenance import stamp

APP = Path(__file__).resolve().parent.parent / "app.py"
FAKE = {
    "success": True, "ports": [], "source_name": "IMF Portwatch", "source_url": "https://portwatch.imf.org",
    "congestion_signals": {"Singapore": "Stable", "Fujairah": "Stable"}, "congestion_reasons": {},
    "provenance": stamp(portwatch.PORTWATCH, as_of=datetime.now(timezone.utc)),
}


def html(at) -> str:
    return "\n".join(m.value for m in at.markdown)


class BunkeringPageTests(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE)
        self.patch.start()
        self.at = AppTest.from_file(str(APP), default_timeout=60).run()
        radio = self.at.sidebar.radio[0]
        radio.set_value("Bunkering strategy").run()
        self.at.button(key="preset_Fujairah unreachable").click().run()

    def tearDown(self):
        self.patch.stop()

    def test_demo_scenario_2_matches_the_readme(self):
        self.assertEqual(len(self.at.exception), 0)
        page = html(self.at)
        # Recommended card first, then the removed Fujairah option with rule F1.
        rec = page.index('class="rec-card')
        self.assertIn("Full bunker — Singapore", page[rec:rec + 600])
        self.assertIn("<b>F1</b>fuel safety reserve not met", page)
        self.assertIn("Full bunker — Fujairah: needs at least 405 MT on board (you have 280 MT).", page)

    def test_step_inputs_survive_moving_between_steps(self):
        self.at.number_input(key="bkw_fuel").set_value(350.0).run()
        self.at.button(key="step_next").click().run()          # step 2: fuel input not drawn
        self.at.button(key="step_back").click().run()          # back to step 1
        self.assertEqual(self.at.number_input(key="bkw_fuel").value, 350.0)
        self.assertEqual(self.at.session_state["bk"]["fuel"], 350.0)

    def test_breakdown_and_compare(self):
        self.at.button(key="det_SGP_FULL").click().run()
        self.assertIn("Score breakdown · Full bunker — Singapore", html(self.at))
        self.at.checkbox(key="cmp_SGP_FULL").check().run()
        self.at.checkbox(key="cmp_SGP_PARTIAL").check().run()
        self.assertIn('class="cmp-table"', html(self.at))
        self.assertEqual(len(self.at.exception), 0)


if __name__ == "__main__":
    unittest.main()
