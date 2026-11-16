"""
tests/test_ui_market_intelligence.py

The Market intelligence page renders the morning brief's payload. It is built
live by modules.morning_brief (patched here with the recorded example payload,
so no network). The page must show every section's state, write figures and
changes exactly as the payload gives them, show news as headline and link only,
and never leak the EIA key in an error.
"""

import copy
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from modules import portwatch
from modules.morning_brief import payload as payload_module
from modules.provenance import stamp

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
PAYLOAD = json.loads((ROOT / "tests/fixtures/payload/from_fixtures.json").read_text(encoding="utf-8"))
FAKE_PW = {
    "success": True, "ports": [], "source_name": "IMF Portwatch", "source_url": "https://portwatch.imf.org",
    "congestion_signals": {"Singapore": "Stable", "Fujairah": "Stable"}, "congestion_reasons": {},
    "provenance": stamp(portwatch.PORTWATCH, as_of=datetime.now(timezone.utc)),
}


def open_mi(build):
    with mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE_PW), \
         mock.patch.object(payload_module, "fetch_and_build", build):
        at = AppTest.from_file(APP, default_timeout=60).run()
        radio = at.sidebar.radio[0]
        radio.set_value("Market intelligence").run()
    return at


def html(at) -> str:
    return "\n".join(str(m.value) for m in list(at.markdown) + list(at.error) + list(at.caption))


class MarketIntelligencePage(unittest.TestCase):
    def test_renders_every_section_from_the_payload(self):
        at = open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD)))
        self.assertEqual(len(at.exception), 0)
        page = html(at)
        self.assertIn("Morning brief · 12 October 2026", page)
        self.assertIn("Trial — under review", page)
        for title in ("Prices", "Freight", "Sources"):
            self.assertIn(title, page)
        # Figures and changes appear exactly as the payload writes them; prices are coloured from the buyer's view.
        self.assertIn("USD 125.44/bbl", page)
        self.assertIn('<span class="mb-dir dir-down">Down</span>USD 0.07/bbl · 0.06% · vs 5 October 2026 (previous published day)', page)
        self.assertIn('<span class="mb-dir dir-up">Up</span>USD 11.48/bbl · 10.07% · vs 29 September 2026 (one week earlier)', page)
        # Volumes get the word only, no colour.
        self.assertIn('<span class="mb-dir">Down</span>46.29 thousand tonnes · 0.97% · vs August 2026 (previous month)', page)
        # Every figure carries its source tag.
        self.assertIn('as of 6 October 2026<span class="mb-tag">[S1]</span>', page)

    def test_not_covered_section_states_its_reason(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        self.assertIn("NOT COVERED", page)
        self.assertIn("No container freight index can be republished", page)

    def test_news_is_headline_and_link_only_with_credit(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        self.assertIn("Port strike talks resume on the US Gulf Coast", page)
        self.assertIn('href="https://gcaptain.com/test-reuters-no-author/"', page)
        self.assertIn("gCaptain · via Reuters · 12 October 2026", page)
        self.assertIn("by Jane Example", page)                                  # author credited when named
        # Feed excerpts can quote licensed figures, so none is ever shown.
        self.assertNotIn("Owners were reluctant to fix forward", page)

    def test_portwatch_activity_carries_the_imf_credit(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        self.assertIn("Suez Canal transits", page)
        self.assertIn(portwatch.PORTWATCH_CREDIT, page)

    def test_a_missing_section_says_so_with_the_reason(self):
        data = copy.deepcopy(PAYLOAD)
        data["sections"]["prices"].update(status="missing", items=[], reason="No EIA API key is configured.")
        page = html(open_mi(mock.Mock(return_value=data)))
        self.assertIn('<span class="missing-badge">MISSING</span>No EIA API key is configured.', page)
        self.assertNotIn("USD 125.44/bbl", page)

    def test_a_failed_build_shows_an_error_and_never_the_key(self):
        secret = "SECRETKEY987"
        boom = mock.Mock(side_effect=RuntimeError(f"GET https://api.eia.gov/x?api_key={secret} failed; key {secret}"))
        with mock.patch.dict(os.environ, {"EIA_API_KEY": secret}):
            at = open_mi(boom)
        self.assertEqual(len(at.exception), 0)
        page = html(at)
        self.assertIn("ERROR — The morning brief could not be built", page)
        self.assertNotIn(secret, page)

    def test_without_network_the_page_still_renders(self):
        # Unpatched: the real fetchers run, the test harness blocks the network, and the
        # page must still render (sections marked missing, or the build error), not crash.
        with mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE_PW):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.sidebar.radio[0].set_value("Market intelligence").run()
        self.assertEqual(len(at.exception), 0)


if __name__ == "__main__":
    unittest.main()


class DataInputValidation(unittest.TestCase):
    def test_no_rows_means_no_passed_checks(self):
        # "PASSED — all 0 rows populated" was shown for every column with nothing loaded.
        with mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE_PW):
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.sidebar.radio[0].set_value("Data input").run()
        self.assertEqual(len(at.exception), 0)
        page = html(at) + " ".join(str(i.value) for i in at.info)
        self.assertIn("No market rows loaded.", page)
        self.assertNotIn("all 0 rows populated", page)
