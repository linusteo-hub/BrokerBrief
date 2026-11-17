"""
tests/test_morning_brief_bunker_sales.py

MPA bunker sales fetcher, run on a recorded data.gov.sg response
(tests/fixtures/mpa/bunker_sales_ok.json, recorded 12-11-2026: the newest 14
months, August 2025 to September 2026) through a stand-in getter — no
network. The error fixtures are hand-made from it.
"""

from datetime import date

import pytest

from modules.morning_brief.allowlist import ALLOWLIST, SourceNotAllowed
from modules.morning_brief.bunker_sales import (
    FIGURES, FUEL_TYPES, build_figures, fetch_bunker_sales, month_display, month_end, parse_records, shift_month,
)
from modules.morning_brief.guarded_http import guarded_get
from tests.fixture_http import serve

TODAY = date(2026, 11, 12)
IDS = [figure_id for figure_id, _, _ in FIGURES]


def fetch(fixture="mpa/bunker_sales_ok.json", status=200, today=TODAY):
    return fetch_bunker_sales(today, get=serve(fixture, status))


def by_id(result):
    return {item["id"]: item for item in result["items"]}


def test_recorded_response_builds_every_figure():
    result = fetch()
    assert result["error"] is None and result["excluded"] == []
    assert [item["id"] for item in result["items"]] == IDS
    total = by_id(result)["sg_bunker_total"]
    assert total["display"] == "4,726.39 thousand tonnes"
    assert total["as_of_display"] == "September 2026" and total["period"] == "month"
    assert total["source_id"] == "mpa_bunker_sales"


def test_total_equals_the_sum_of_mpas_types_and_the_changes_are_precomputed():
    total = by_id(fetch())["sg_bunker_total"]
    month, year = total["changes"]
    assert (month["basis"], month["compared_with"], month["previous_display"]) == (
        "previous month", "August 2026", "4,772.68 thousand tonnes")
    assert (month["abs_display"], month["pct_display"], month["direction"]) == (
        "46.29 thousand tonnes", "0.97%", "down")
    assert (year["basis"], year["compared_with"], year["previous_display"], year["direction"]) == (
        "same month a year earlier", "September 2025", "4,765.08 thousand tonnes", "down")
    # MPA's own total series gives 4,765.09 for September 2025: summing rounded components
    # can differ by 0.01, which is why the label says this is BrokerBrief's sum.


def test_component_figures_use_mpas_own_types():
    figures = by_id(fetch())
    assert figures["sg_bunker_lsfo"]["display"] == "2,218.11 thousand tonnes"
    assert figures["sg_bunker_mfo"]["display"] == "1,993.20 thousand tonnes"
    assert figures["sg_bunker_lsmgo"]["display"] == "378.84 thousand tonnes"
    assert figures["sg_bunker_lng"]["display"] == "51.51 thousand tonnes"
    # 4.33 + 0.1 + 76.2 bio-blended + 2.58 B100; labelled as our own sum.
    assert figures["sg_bunker_bio"]["display"] == "83.21 thousand tonnes"
    assert "BrokerBrief sum" in figures["sg_bunker_bio"]["label"]


def test_a_value_in_plain_tonnes_is_refused_not_published():
    result = fetch("mpa/out_of_range.json")
    assert result["items"] == []
    assert {e["id"] for e in result["excluded"]} == set(IDS)
    assert all(e["code"] == "out_of_range" and "outside the plausible range" in e["reason"]
               for e in result["excluded"])


def test_incomplete_latest_month_is_excluded_with_the_missing_type_named():
    result = fetch("mpa/latest_month_incomplete.json")
    assert result["items"] == []
    assert all(e["code"] == "incomplete" for e in result["excluded"])
    assert "lack 1 of 16 fuel types (LNG)" in result["excluded"][0]["reason"]


def test_stale_month_is_excluded():
    # September 2026 ends 30-09; the limit is 62 days, so 2 December is too late.
    assert fetch(today=date(2026, 12, 1))["items"]
    late = fetch(today=date(2026, 12, 2))
    assert late["items"] == [] and all(e["code"] == "stale" for e in late["excluded"])
    assert "limit 62 days" in late["excluded"][0]["reason"]


@pytest.mark.parametrize("fixture,status", [
    ("mpa/malformed.html", 200), ("mpa/api_error.json", 200), ("mpa/bunker_sales_ok.json", 503),
])
def test_feed_failures_are_reported_never_raised(fixture, status):
    result = fetch(fixture, status)
    assert result["items"] == [] and result["error"]
    assert [e["code"] for e in result["excluded"]] == ["feed_failed"] * len(IDS)


def test_empty_response_is_no_data():
    result = fetch("mpa/empty.json")
    assert result["items"] == [] and all(e["code"] == "no_data" for e in result["excluded"])


def test_comparison_month_missing_drops_that_change_only():
    import json
    from tests.fixture_http import FIXTURES
    records = json.loads((FIXTURES / "mpa/bunker_sales_ok.json").read_text())["result"]["records"]
    months = parse_records(records)
    del months["2025-09"]
    figures, excluded = build_figures(months, TODAY)
    assert excluded == []
    assert [c["basis"] for c in figures[0]["changes"]] == ["previous month"]


def test_month_helpers():
    assert month_end("2026-02") == date(2026, 2, 28) and month_end("2024-02") == date(2024, 2, 29)
    assert month_display("2026-09") == "September 2026"
    assert shift_month("2026-01", -1) == "2025-12" and shift_month("2026-09", -12) == "2025-09"
    assert len(FUEL_TYPES) == 16


def test_rows_with_bad_values_are_skipped():
    months = parse_records([{"month": "2026-09", "bunker_type": "LNG", "bunker_sales": "na"},
                            {"month": "bad", "bunker_type": "LNG", "bunker_sales": "1"},
                            {"month": "2026-09", "bunker_type": "B100", "bunker_sales": "2.58"}])
    assert months == {"2026-09": {"B100": 2.58}}


def test_source_is_allowlisted_as_redistributable_data_with_the_licence_notice():
    source = ALLOWLIST["mpa_bunker_sales"]
    assert source.kind == "data" and source.redistributable
    assert "Singapore Open Data Licence version 1.0" in source.credit
    assert source.terms_url == "https://data.gov.sg/open-data-licence"


def test_only_the_allowlisted_endpoint_can_be_requested():
    with pytest.raises(SourceNotAllowed):
        guarded_get("https://data.gov.sg/api/action/package_search")
