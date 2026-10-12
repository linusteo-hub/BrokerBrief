"""
tests/test_morning_brief_payload.py

End-to-end payload build on fixture responses (no network): section status
for good, stale, out-of-range and missing feeds, source tagging, and the
final gate refusing non-allowlisted or banned content.

tests/fixtures/payload/from_fixtures.json is the payload built from the
recorded fixtures. If a deliberate change alters it, regenerate with:
    UPDATE_PAYLOAD_FIXTURE=1 pytest tests/test_morning_brief_payload.py
"""

import json
import os
import re
from datetime import datetime, timezone

import pytest

from modules.morning_brief.allowlist import SourceNotAllowed
from modules.morning_brief.payload import build_payload, fetch_and_build, final_gate, iter_items
from tests.fixture_http import FIXTURES, serve_by

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

RECORDED = {
    "api.eia.gov": lambda p: "eia/brent_ok.json" if p.get("facets[series][]") == "RBRTE" else "eia/ulsd_ok.json",
    "Daily_Chokepoints_Data": lambda p: "portwatch/chokepoints_ok.json",
    "Daily_Ports_Data": lambda p: "portwatch/ports_ok.json",
    "gcaptain.com": lambda p: "news/special_cases.xml",
    "splash247.com": lambda p: "news/splash_sanitised.xml",
    "maritime-executive.com": lambda p: "news/marex_sanitised.xml",
}


def getter(**overrides):
    """Serve the recorded fixture for each URL; overrides: key -> (fixture[, status])."""
    def choose(url, params):
        key = next(k for k in RECORDED if k in url)
        if key in overrides:
            return overrides[key]
        return (RECORDED[key](params),)
    return serve_by(choose)


def build(now=NOW, key="key", **overrides):
    return fetch_and_build(now=now, eia_api_key=key, get=getter(**overrides))


def test_all_sections_ok_from_recorded_fixtures():
    payload = build()
    sections = payload["sections"]
    assert {k: s["status"] for k, s in sections.items()} == {
        "prices": "ok", "freight": "ok", "sale_and_purchase": "ok", "events": "ok"}
    assert sections["freight"]["subsections"]["container_rates"]["status"] == "not_covered"
    assert payload["brief_date_display"] == "12 October 2026"
    assert payload["trial_notice"] == "Trial — under review"


def test_every_item_has_a_listed_source_tag_and_figures_have_directions():
    payload = build()
    tags = {s["tag"] for s in payload["sources"]}
    for item, is_figure in iter_items(payload):
        assert item["source_tag"] in tags
        if is_figure:
            assert all(c["direction"] in {"up", "down", "flat"} for c in item["changes"])
    credits = {s["id"]: s["credit"] for s in payload["sources"]}
    assert credits["imf_portwatch"].startswith("BrokerBrief calculations based on data from International Monetary Fund")


def test_stale_prices_mark_section_missing_with_reason():
    # Recorded EIA and PortWatch data read on 30-10-2026 are too old.
    payload = build(now=datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc))
    prices = payload["sections"]["prices"]
    assert prices["status"] == "missing" and "limit 10 days" in prices["reason"]
    assert payload["sections"]["freight"]["subsections"]["activity"]["status"] == "missing"


def test_out_of_range_price_is_excluded_and_recorded():
    payload = build(**{"api.eia.gov": ("eia/brent_out_of_range.json",)})
    # Both series get the out-of-range Brent file here, so neither passes.
    assert payload["sections"]["prices"]["status"] == "missing"
    assert "outside the plausible range" in payload["sections"]["prices"]["reason"]
    assert payload["validation"]["excluded_figures"]


def test_missing_feeds_mark_sections_missing_not_fabricated():
    bad = ("news/malformed.xml",)
    payload = build(key=None, **{"gcaptain.com": bad, "splash247.com": bad, "maritime-executive.com": bad,
                                 "Daily_Chokepoints_Data": ("portwatch/arcgis_error.json",),
                                 "Daily_Ports_Data": ("portwatch/empty.json", 503)})
    sections = payload["sections"]
    assert all(s["status"] == "missing" for s in sections.values())
    assert "EIA_API_KEY" in sections["prices"]["reason"]
    assert sections["events"]["reason"].startswith("every news feed failed")
    assert all(not s["items"] for k, s in sections.items() if k != "freight")
    assert set(payload["validation"]["feed_errors"]) == {
        "eia_spot", "imf_portwatch", "gcaptain", "splash247", "maritime_executive"}


def _empty_results():
    return dict(prices={"items": [], "excluded": [], "error": None},
                activity={"items": [], "excluded": [], "error": None},
                news={"sections": {"freight": [], "sale_and_purchase": [], "events": []},
                      "dropped": [], "feed_errors": {}})


def test_non_allowlisted_source_is_refused():
    results = _empty_results()
    results["prices"]["items"] = [{"id": "x", "display": "USD 1.00/bbl", "changes": [], "source_id": "some_blog"}]
    with pytest.raises(SourceNotAllowed, match="not on the morning-brief allowlist"):
        build_payload(now=NOW, **results)


def test_numbers_from_news_source_are_refused():
    results = _empty_results()
    results["prices"]["items"] = [{"id": "x", "display": "USD 1.00/bbl", "changes": [], "source_id": "gcaptain"}]
    with pytest.raises(SourceNotAllowed, match="not redistributable"):
        build_payload(now=NOW, **results)


def test_final_gate_refuses_digit_in_excerpt_and_wire_summary():
    payload = build()
    news_item = next(i for i, fig in iter_items(payload) if not fig and i["excerpt"])
    news_item["excerpt"] = "Rates rose 5 percent."
    with pytest.raises(ValueError, match="digit"):
        final_gate(payload)

    payload = build()
    wire = next(i for i, fig in iter_items(payload) if not fig and i["wire_agency"])
    wire["excerpt"] = "A summary of wire copy."
    with pytest.raises(ValueError, match="headline and link only"):
        final_gate(payload)


def test_final_gate_refuses_banned_name_anywhere():
    banned_text = json.loads((FIXTURES / "banned_sources.json").read_text())["texts_that_must_match"][0]
    payload = build()
    next(i for i, fig in iter_items(payload) if not fig)["headline"] = banned_text
    with pytest.raises(SourceNotAllowed, match="banned source"):
        final_gate(payload)


def test_payload_has_no_digits_in_any_news_excerpt():
    payload = build()
    assert all(not re.search(r"\d", i.get("excerpt") or "") for i, fig in iter_items(payload) if not fig)


def test_payload_from_fixtures_matches_saved_example():
    payload = build()
    path = FIXTURES / "payload" / "from_fixtures.json"
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_PAYLOAD_FIXTURE"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == payload
