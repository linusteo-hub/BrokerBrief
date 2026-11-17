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
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import requests
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
        # Figures and changes appear exactly as the payload writes them. Direction is an arrow with the
        # word for screen readers (no red or green); the full basis and date are in the chip's title.
        self.assertIn("USD 125.44/bbl", page)
        self.assertIn('<span class="mb-chip" title="vs 5 October 2026 (previous published day)">', page)
        self.assertIn('<span class="sr-only">Down</span></span><span class="mb-chip-key">1D</span>USD 0.07/bbl · 0.06%', page)
        self.assertIn('<span class="sr-only">Up</span></span><span class="mb-chip-key">1W</span>USD 11.48/bbl · 10.07%', page)
        self.assertNotIn('class="mb-dir dir-up"', page)
        self.assertNotIn('class="mb-dir dir-down"', page)
        # Bunker sales in whole tonnes (MT), with short names.
        self.assertIn('<span class="mb-chip-key">1M</span>46,290 MT · 0.97%', page)
        self.assertIn('<div class="mb-stat-value">4,726,390 MT</div>', page)
        self.assertIn(">All fuels</div>", page)
        # The shared date and source tag are printed once per card.
        self.assertIn('6 October 2026<span class=mb-tag>[S1]</span></span>', page)
        self.assertIn('September 2026<span class=mb-tag>[S2]</span></span>', page)

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

    def test_every_section_and_subsection_title_is_shown(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        for title in ("Prices", "Singapore bunker sales", "Freight", "Sale &amp; Purchase", "Events",
                      "Container freight rates", "Freight rate direction (from news, no figures)",
                      "Ship activity (transits and port calls, not rates)", "Sources"):
            self.assertIn(title, page)

    def test_a_change_with_no_percentage_still_renders(self):
        # pct_display is None when the previous value is 0; it once crashed the whole page.
        data = copy.deepcopy(PAYLOAD)
        change = data["sections"]["prices"]["items"][0]["changes"][0]
        change.update(pct_display=None, pct_change=None, previous_value=0)
        at = open_mi(mock.Mock(return_value=data))
        self.assertEqual(len(at.exception), 0)
        page = html(at)
        self.assertIn('<span class="mb-chip-key">1D</span>USD 0.07/bbl<span class="sr-only">', page)
        self.assertNotIn("None", page)

    def test_source_notes_are_shown_once(self):
        # MPA's "preliminary" warning belongs beside the bunker-sales figures, once, not six times.
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        self.assertEqual(page.count("preliminary estimates"), 1)

    def test_only_https_links_are_rendered(self):
        data = copy.deepcopy(PAYLOAD)
        item = data["sections"]["events"]["items"][0]
        item["link"] = "javascript:alert(1)"
        data["sources"][0]["url"] = "http://example.org/"
        page = html(open_mi(mock.Mock(return_value=data)))
        self.assertIn(item["headline"], page)
        self.assertNotIn("javascript:", page)
        self.assertNotIn('href="http://', page)

    def test_an_unknown_section_is_shown_not_dropped(self):
        data = copy.deepcopy(PAYLOAD)
        data["sections"]["new_section"] = {"title": "Port state control", "status": "missing",
                                           "reason": "Not built yet.", "items": []}
        page = html(open_mi(mock.Mock(return_value=data)))
        self.assertIn("Port state control", page)
        self.assertIn("Not built yet.", page)

    def test_a_brief_with_a_feed_error_is_rebuilt_after_five_minutes(self):
        # A feed outage must not be served for 3 hours: it is held 5 minutes, then rebuilt.
        data = copy.deepcopy(PAYLOAD)
        data["validation"]["feed_errors"] = {"gcaptain": "HTTP 503"}
        build = mock.Mock(return_value=data)
        at = open_mi(build)
        with mock.patch.object(payload_module, "fetch_and_build", build), \
             mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE_PW):
            at.run()                                                   # within 5 minutes: the held brief
            self.assertEqual(build.call_count, 1)
            later = time.monotonic() + 6 * 60
            with mock.patch("time.monotonic", return_value=later):
                at.run()
        self.assertEqual(build.call_count, 2)
        self.assertEqual(len(at.exception), 0)

    def test_a_failed_feed_is_named_on_the_page(self):
        data = copy.deepcopy(PAYLOAD)
        data["validation"]["feed_errors"] = {"gcaptain": "HTTP 503"}
        page = html(open_mi(mock.Mock(return_value=data)))
        self.assertIn("Feeds that failed in this build", page)
        self.assertIn("gCaptain (HTTP 503)", page)

    def test_a_missing_eia_key_alone_does_not_trigger_rebuilds(self):
        # Retrying cannot fix a missing key, so that brief is kept like a clean one.
        data = copy.deepcopy(PAYLOAD)
        data["validation"]["feed_errors"] = {"eia_spot": "no EIA API key configured (set EIA_API_KEY)"}
        build = mock.Mock(return_value=data)
        with mock.patch.dict(os.environ, {"EIA_API_KEY": ""}):
            at = open_mi(build)
            with mock.patch.object(payload_module, "fetch_and_build", build), \
                 mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE_PW), \
                 mock.patch("time.monotonic", return_value=time.monotonic() + 6 * 60):
                at.run()
        self.assertEqual(build.call_count, 1)
        self.assertNotIn("Feeds that failed", html(at))

    def test_a_clean_brief_is_kept(self):
        build = mock.Mock(return_value=copy.deepcopy(PAYLOAD))
        at = open_mi(build)
        with mock.patch.object(payload_module, "fetch_and_build", build), \
             mock.patch.object(portwatch, "fetch_port_activity", return_value=FAKE_PW), \
             mock.patch("time.monotonic", return_value=time.monotonic() + 6 * 60):
            at.run()
        self.assertEqual(build.call_count, 1)

    def test_offline_every_feed_is_marked_missing_not_crashed(self):
        # The real fetchers run with a getter that cannot reach the network.
        real = payload_module.fetch_and_build

        def offline_get(*args, **kwargs):
            raise requests.ConnectionError("network unreachable (test)")

        def build(**kwargs):
            kwargs["get"] = offline_get
            return real(**kwargs)

        with mock.patch.dict(os.environ, {"EIA_API_KEY": "TESTKEY123"}):
            at = open_mi(build)
        self.assertEqual(len(at.exception), 0)
        page = html(at)
        self.assertNotIn("TESTKEY123", page)
        self.assertIn("MISSING", page)
        self.assertNotIn("USD 125.44/bbl", page)


class MarketIntelligenceCharts(unittest.TestCase):
    def test_price_lines_and_bunker_bars_are_drawn_from_the_series(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        self.assertEqual(page.count('<div class="ch ch-line"'), 2)
        # Hover text is the payload's own display strings: the newest point is the figure itself.
        self.assertIn("<b>USD 125.44/bbl</b>6 October 2026", page)
        self.assertIn("<b>4,726,390 MT</b>September 2026", page)
        self.assertEqual(page.count('<div class="ch ch-bars'), 6)          # total full size, five compact
        self.assertEqual(page.count('class="ch-bar'), 6 * 13)

    def test_a_dropped_series_says_why_instead_of_drawing(self):
        data = copy.deepcopy(PAYLOAD)
        fig = data["sections"]["prices"]["items"][0]
        fig.update(series=None, series_note="USD 5.00/bbl on 1 October 2026 is outside the plausible range 10–300, so no chart is drawn")
        page = html(open_mi(mock.Mock(return_value=data)))
        self.assertIn("No chart: USD 5.00/bbl on 1 October 2026 is outside the plausible range", page)
        self.assertEqual(page.count('<div class="ch ch-line"'), 1)

    def test_timeline_places_every_dated_headline_in_its_section_lane(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        sec = PAYLOAD["sections"]
        news = (sec["freight"]["subsections"]["rate_direction"]["items"] + sec["sale_and_purchase"]["items"]
                + sec["events"]["items"])
        self.assertIn("News flow", page)
        self.assertEqual(page.count("<li>"), sum(1 for i in news if i.get("published")))   # every headline listed
        self.assertIn('<div class="nf-name">Sale &amp; Purchase</div>', page)


class TimelineStacking(unittest.TestCase):
    def test_headlines_close_in_time_merge_into_one_mark_that_lists_them_all(self):
        from modules import ui
        items = [{"headline": f"H{i}", "published": "2026-10-12T09:00:00+00:00", "link": "https://example.org/"}
                 for i in range(3)] + [{"headline": "Early", "published": "2026-10-11T10:00:00+00:00"}]
        out = ui.news_timeline([("Events", items)], "2026-10-11T09:00:00+00:00", "2026-10-12T12:00:00+00:00")
        self.assertEqual(out.count('class="nf-tick'), 2)
        self.assertIn('aria-label="Events: 3 headlines"', out)
        self.assertIn('aria-label="Events: 1 headline"', out)
        for i in range(3):
            self.assertIn(f'<a href="https://example.org/" target="_blank" rel="noopener noreferrer">H{i}</a>', out)
        self.assertIn("<span>Early</span>", out)               # no link: shown, not linked
        self.assertIn('<div class="nf-count">4</div>', out)


class ChartBuilders(unittest.TestCase):
    def test_undrawable_series_render_nothing_instead_of_crashing(self):
        from modules import ui
        one = {"points": [{"date": "2026-10-06", "date_display": "6 October 2026", "value": 1.0, "display": "1"}]}
        bad = {"points": [{"date": "2026-10-05", "value": 1.0, "display": "1"},
                          {"date": "2026-10-06", "date_display": "6 October 2026", "value": 2.0, "display": 2}]}
        for series in (one, bad, None, {}):
            self.assertEqual(ui.line_chart(series), "")
            self.assertEqual(ui.bar_chart(series), "")

    def test_tooltips_are_hidden_from_screen_readers(self):
        page = html(open_mi(mock.Mock(return_value=copy.deepcopy(PAYLOAD))))
        self.assertNotIn('<span class="ch-tip">', page)
        self.assertIn('<span class="ch-tip" aria-hidden="true">', page)

    def test_line_points_are_placed_by_date_and_the_first_sits_at_the_left_edge(self):
        from modules import ui
        pts = [{"date": d, "date_display": d, "value": v, "display": str(v)}
               for d, v in (("2026-10-01", 1.0), ("2026-10-02", 2.0), ("2026-10-09", 3.0))]
        out = ui.line_chart({"points": pts}, uid="t")
        self.assertIn("M0.00,", out)
        self.assertIn(" L12.50,", out)                      # 1 day of 8
        self.assertIn('id="ch-fade-t"', out)

    def test_an_empty_lane_shows_its_section_reason(self):
        from modules import ui
        out = ui.news_timeline([("Events", [], "no events stories met the rules")],
                               "2026-10-11T09:00:00+00:00", "2026-10-12T12:00:00+00:00")
        self.assertIn('<span class="nf-empty">no events stories met the rules</span>', out)


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


if __name__ == "__main__":
    unittest.main()
