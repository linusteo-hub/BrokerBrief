"""
tests/test_morning_brief_activity.py

PortWatch activity fetcher, run on recorded PortWatch responses
(tests/fixtures/portwatch/, recorded 12-10-2026) plus hand-made error
fixtures, through a stand-in getter — no network.
"""

import json
from datetime import date

from modules.morning_brief.activity import CHOKEPOINTS, PORTS, fetch_activity, weekly_figures
from modules.morning_brief.figures import count
from tests.fixture_http import FIXTURES, serve, serve_by

TODAY = date(2026, 10, 12)


def recorded(url, params):
    return ("portwatch/chokepoints_ok.json",) if "Chokepoints" in url else ("portwatch/ports_ok.json",)


def recorded_rows(name):
    return [f["attributes"] for f in json.loads((FIXTURES / f"portwatch/{name}.json").read_text())["features"]]


def by_id(result):
    return {item["id"]: item for item in result["items"]}


def test_recorded_responses_build_weekly_totals():
    result = fetch_activity(TODAY, get=serve_by(recorded))
    assert result["error"] is None and result["excluded"] == []
    figures = by_id(result)
    assert len(figures) == len(CHOKEPOINTS) + len(PORTS)

    suez = figures["transits_chokepoint1"]
    assert suez["label"] == "Suez Canal transits, 7 days to 4 October 2026"
    assert suez["display"] == "302 transits"
    change = suez["changes"][0]
    assert (change["abs_display"], change["pct_display"], change["direction"]) == ("22 transits", "7.86%", "up")
    assert change["compared_with"] == "7 days to 27 September 2026"

    houston = figures["portcalls_port481"]
    assert houston["label"].startswith("Houston port calls")   # found by portid, not by name
    assert houston["as_of"] == "2026-10-02"


def test_singular_count():
    assert count("transits")(1) == "1 transit"
    assert count("port calls")(1_584) == "1,584 port calls"


def test_stale_data_is_excluded():
    result = fetch_activity(date(2026, 10, 30), get=serve_by(recorded))
    assert result["items"] == []
    assert all("limit 14 days" in e["reason"] for e in result["excluded"])


def test_location_with_missing_day_is_excluded_not_compared():
    rows = [r for r in recorded_rows("chokepoints_ok")
            if not (r["portid"] == "chokepoint1" and r["date"] == "2026-10-01")]
    figures, excluded = weekly_figures(rows, CHOKEPOINTS, "n_total", "transits", "transits", TODAY)
    assert "transits_chokepoint1" not in {f["id"] for f in figures}
    assert excluded == [{"id": "transits_chokepoint1",
                         "reason": "Suez Canal: 1 of 14 days missing, so the weeks cannot be compared"}]


def test_out_of_range_total_is_excluded():
    rows = recorded_rows("chokepoints_ok")
    for r in rows:
        if r["portid"] == "chokepoint2":
            r["n_total"] = 5_000          # 7 x 5,000 is beyond any plausible week
    figures, excluded = weekly_figures(rows, CHOKEPOINTS, "n_total", "transits", "transits", TODAY)
    assert [e["id"] for e in excluded] == ["transits_chokepoint2"]
    assert "outside the plausible range" in excluded[0]["reason"]


def test_empty_response_excludes_every_location():
    result = fetch_activity(TODAY, get=serve("portwatch/empty.json"))
    assert result["items"] == []
    assert len(result["excluded"]) == len(CHOKEPOINTS) + len(PORTS)


def test_arcgis_error_body_is_a_failed_feed():
    # ArcGIS sends query errors with HTTP 200.
    result = fetch_activity(TODAY, get=serve("portwatch/arcgis_error.json"))
    assert result["items"] == [] and "ArcGIS error" in result["error"]


def test_malformed_response_is_a_failed_feed():
    result = fetch_activity(TODAY, get=serve("portwatch/malformed.txt"))
    assert result["items"] == [] and "request failed" in result["error"]


def test_one_layer_failing_keeps_the_other():
    def mixed(url, params):
        return ("portwatch/chokepoints_ok.json",) if "Chokepoints" in url else ("portwatch/empty.json", 500)
    result = fetch_activity(TODAY, get=serve_by(mixed))
    assert len(result["items"]) == len(CHOKEPOINTS)
    assert "ports request failed" in result["error"]
