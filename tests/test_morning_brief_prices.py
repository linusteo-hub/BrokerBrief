"""
tests/test_morning_brief_prices.py

EIA price fetcher, run on recorded EIA responses (tests/fixtures/eia/) through
a stand-in getter — no network. brent_ok.json / ulsd_ok.json were recorded on
12-10-2026; the error fixtures are hand-made.
"""

from datetime import date

import pytest

from modules.eia import _redact
from modules.morning_brief.allowlist import SourceNotAllowed
from modules.morning_brief.figures import make_change, money
from modules.morning_brief.guarded_http import guarded_get
from modules.morning_brief.prices import fetch_prices, parse_rows
from tests.fixture_http import serve, serve_by

TODAY = date(2026, 10, 12)


def recorded(url, params):
    series = params["facets[series][]"]
    return ("eia/brent_ok.json",) if series == "RBRTE" else ("eia/ulsd_ok.json",)


def by_id(result):
    return {item["id"]: item for item in result["items"]}


def test_recorded_responses_build_both_figures():
    result = fetch_prices("key", TODAY, get=serve_by(recorded))
    assert result["excluded"] == [] and result["error"] is None
    brent, ulsd = by_id(result)["brent_spot"], by_id(result)["ulsd_nyh"]

    assert brent["display"] == "USD 125.44/bbl"
    assert brent["as_of_display"] == "6 October 2026"
    day, week = brent["changes"]
    assert (day["compared_with"], day["abs_display"], day["pct_display"], day["direction"]) == (
        "5 October 2026", "USD 0.07/bbl", "0.06%", "down")
    assert (week["compared_with"], week["abs_display"], week["direction"]) == (
        "29 September 2026", "USD 11.48/bbl", "up")

    assert ulsd["display"] == "USD 4.713/gal"
    assert ulsd["changes"][0]["direction"] == "up"


def test_stale_recorded_value_is_excluded():
    # Same recorded data, read 24 days after its newest value (limit is 10 days).
    result = fetch_prices("key", date(2026, 10, 30), get=serve_by(recorded))
    assert result["items"] == []
    assert all("24 days old" in e["reason"] for e in result["excluded"])


def test_out_of_range_value_is_excluded():
    result = fetch_prices("key", TODAY, get=serve_by(
        lambda url, p: ("eia/brent_out_of_range.json",) if p["facets[series][]"] == "RBRTE"
        else ("eia/ulsd_ok.json",)))
    assert list(by_id(result)) == ["ulsd_nyh"]
    assert "outside the plausible range" in result["excluded"][0]["reason"]


def test_empty_response_is_excluded_with_reason():
    result = fetch_prices("key", TODAY, get=serve("eia/empty.json"))
    assert result["items"] == []
    assert all(e["reason"] == "EIA returned no usable values" for e in result["excluded"])


@pytest.mark.parametrize("fixture", ["eia/malformed.html", "eia/wrong_shape.json"])
def test_malformed_response_is_a_failed_request(fixture):
    result = fetch_prices("key", TODAY, get=serve(fixture))
    assert result["items"] == []
    assert all(e["reason"].startswith("EIA request failed") for e in result["excluded"])


def test_http_error_is_a_failed_request():
    result = fetch_prices("key", TODAY, get=serve("eia/empty.json", status=503))
    assert all("503" in e["reason"] for e in result["excluded"])


def test_missing_api_key_is_a_feed_error():
    result = fetch_prices(None, TODAY)
    assert result["items"] == [] and "EIA_API_KEY" in result["error"]


def test_blank_holiday_values_are_skipped():
    rows = [{"period": "2026-10-06", "value": "125.44"}, {"period": "2026-10-05", "value": None},
            {"period": "2026-10-02", "value": ""}]
    assert parse_rows(rows) == [(date(2026, 10, 6), 125.44)]


def test_direction_follows_the_displayed_change():
    fmt = money("USD/bbl", 2)
    assert make_change(84.204, 84.201, fmt, decimals=2, basis="", compared_with="")["direction"] == "flat"
    assert make_change(84.21, 84.20, fmt, decimals=2, basis="", compared_with="")["direction"] == "up"


def test_api_key_is_redacted_from_errors():
    message = "404 Client Error for url: https://api.eia.gov/v2/x?api_key=SECRET123&frequency=daily"
    assert "SECRET123" not in _redact(message)


def test_guarded_get_refuses_url_outside_allowlist():
    # Raises before any request is attempted (the network is blocked anyway).
    with pytest.raises(SourceNotAllowed, match="not an allowlisted URL"):
        guarded_get("https://example.com/prices.json")


def test_guarded_get_refuses_lookalike_host():
    with pytest.raises(SourceNotAllowed):
        guarded_get("https://api.eia.gov.evil.example/v2/petroleum/pri/spt/data/")


def test_refused_url_is_not_swallowed_by_the_fetcher():
    def refusing_get(url, **kwargs):
        raise SourceNotAllowed("refusing to fetch")
    with pytest.raises(SourceNotAllowed):
        fetch_prices("key", TODAY, get=refusing_get)


def test_network_is_blocked_in_tests():
    import requests
    with pytest.raises(Exception, match="must not use the network"):
        requests.get("https://api.eia.gov/v2/petroleum/pri/spt/data/", timeout=2)
