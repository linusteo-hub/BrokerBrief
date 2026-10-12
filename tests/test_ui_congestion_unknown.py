"""
tests/test_ui_congestion_unknown.py

The app must show an Unknown congestion signal as "Unknown — <reason>", never
blank and never Stable. Runs app.py in Streamlit's test harness with
PortWatch patched (no network).
"""

import unittest
from datetime import datetime, timezone
from unittest import mock

from streamlit.testing.v1 import AppTest

from modules import portwatch
from modules.provenance import stamp

REASON = "Only 1 day of PortWatch data for Fujairah in the last 14 days; at least 2 are needed to compare."
FAKE = {
    "success": True, "ports": [], "source_name": "IMF Portwatch", "source_url": "https://portwatch.imf.org",
    "congestion_signals": {"Singapore": "Stable", "Fujairah": "Unknown"},
    "congestion_reasons": {"Fujairah": REASON},
    "provenance": stamp(portwatch.PORTWATCH, as_of=datetime.now(timezone.utc)),
}


def open_page(name):
    with mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE):
        at = AppTest.from_file("app.py", default_timeout=60).run()
        radio = at.sidebar.radio[0]
        radio.set_value(next(o for o in radio.options if name in o)).run()
    return at


def texts(at):
    return [m.value for m in at.markdown] + [c.value for c in at.caption]


class UnknownCongestionShownTests(unittest.TestCase):
    def test_market_intelligence_shows_unknown_with_reason(self):
        at = open_page("Market Intelligence")
        self.assertEqual(len(at.exception), 0)
        shown = texts(at)
        self.assertIn(f"- **Fujairah**: Unknown — {REASON}", shown)
        self.assertFalse(any("**Fujairah**: Stable" in t for t in shown))
        self.assertTrue(any(t.startswith("Congestion unknown") and REASON in t for t in shown))

    def test_live_data_shows_unknown_with_reason(self):
        at = open_page("Live Data")
        self.assertEqual(len(at.exception), 0)
        self.assertIn(f"⚪ **Fujairah**: Unknown — {REASON}", texts(at))


if __name__ == "__main__":
    unittest.main()
