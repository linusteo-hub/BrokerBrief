"""
tests/test_morning_brief_port_traffic.py

MPA vessel arrivals and calls (data.gov.sg), the brief's port-activity source
since IMF PortWatch's daily data began to require a token. Recorded responses
only; no network.
"""

import json
from datetime import date

import pytest

from modules.morning_brief import port_traffic
from modules.morning_brief.allowlist import ALLOWLIST
from tests.fixture_http import FIXTURES, serve, serve_by

TODAY = date(2026, 10, 25)


def recorded(arrivals=("mpa/vessel_arrivals_ok.json",), calls=("mpa/vessel_calls_ok.json",)):
    return serve_by(lambda url, p: arrivals if p.get("resource_id") == port_traffic.ARRIVALS_RESOURCE else calls)


def by_id(result):
    return {i["id"]: i for i in result["items"]}


def test_recorded_responses_build_every_figure_with_changes_and_chart():
    result = port_traffic.fetch_port_traffic(TODAY, get=recorded())
    assert result["error"] is None and result["excluded"] == []
    figs = by_id(result)
    assert list(figs) == ["sg_vessel_arrivals", "sg_calls_bunkers", "sg_calls_cargo"]
    arrivals = figs["sg_vessel_arrivals"]
    assert (arrivals["display"], arrivals["as_of_display"], arrivals["short_label"]) == (
        "11,608 arrivals", "September 2026", "Vessel arrivals")
    month, year = arrivals["changes"]
    assert (month["basis"], month["compared_with"], month["abs_display"], month["pct_display"], month["direction"]) == (
        "previous month", "August 2026", "23 arrivals", "0.20%", "down")
    assert (year["compared_with"], year["abs_display"], year["direction"]) == ("September 2025", "616 arrivals", "up")
    assert figs["sg_calls_bunkers"]["display"] == "3,617 calls"
    assert figs["sg_calls_cargo"]["display"] == "4,070 calls"
    for fig in figs.values():
        assert fig["source_id"] == "mpa_port_traffic" and "preliminary" in fig["notes"]
        assert len(fig["series"]["points"]) == 13
        assert fig["series"]["points"][-1]["display"] == fig["display"]


def test_purposes_are_never_added_into_a_total():
    # MPA does not say whether one call can count under several purposes.
    assert not any("total" in f[0] and f[3] != "arrivals" for f in port_traffic.FIGURES)


def test_an_out_of_range_value_is_refused_with_the_reason():
    figure, problem = port_traffic.build_figure("x", "X", "X", "calls", (500, 15_000), {"2026-09": 99_999}, TODAY)
    assert figure is None and problem["code"] == "out_of_range"


def test_a_stale_month_is_refused():
    figure, problem = port_traffic.build_figure("x", "X", "X", "calls", (500, 15_000), {"2026-01": 3_000}, TODAY)
    assert figure is None and problem["code"] == "stale"


def test_a_missing_month_ends_the_chart_rather_than_leaving_a_gap():
    months = {f"2026-{m:02d}": 3_500 for m in range(1, 10)}
    del months["2026-05"]
    figure, _ = port_traffic.build_figure("x", "X", "X", "calls", (500, 15_000), months, TODAY)
    assert [p["date"][:7] for p in figure["series"]["points"]] == ["2026-06", "2026-07", "2026-08", "2026-09"]


@pytest.mark.parametrize("fixture", [("mpa/malformed.html",), ("mpa/api_error.json",), ("mpa/empty.json", 503)])
def test_a_broken_feed_marks_every_figure_excluded_never_invented(fixture):
    result = port_traffic.fetch_port_traffic(TODAY, get=serve(*fixture))
    assert result["items"] == [] and result["error"]
    assert {e["id"] for e in result["excluded"]} == {f[0] for f in port_traffic.FIGURES}


def test_source_is_allowlisted_as_redistributable_open_data_with_credit():
    source = ALLOWLIST["mpa_port_traffic"]
    assert source.redistributable and source.kind == "data"
    assert "Singapore Open Data Licence" in source.licence and "data.gov.sg" in source.credit
    assert source.fetch_urls == (port_traffic.API_URL,)


def test_a_failure_test_breaks_only_the_named_mpa_source(monkeypatch):
    # Both MPA datasets share data.gov.sg's URL; each fetcher names its own source.
    from modules.morning_brief import bunker_sales
    from modules.morning_brief.guarded_http import BREAK_FEED_VARIABLE, guarded_get
    monkeypatch.setenv(BREAK_FEED_VARIABLE, "mpa_port_traffic")
    result = port_traffic.fetch_port_traffic(TODAY, get=guarded_get)
    assert result["items"] == [] and "deliberately broken" in result["error"]
    calls = []
    def recording_get(url, params=None, timeout=None, source_id=None, **kw):
        from modules.morning_brief.guarded_http import check_break
        check_break(url, source_id)          # must not raise for bunker sales
        calls.append(source_id)
        raise RuntimeError("stop after the check")
    bunker_sales.fetch_bunker_sales(TODAY, get=recording_get)
    assert calls == ["mpa_bunker_sales"]


def test_a_missing_comparison_month_is_stated_not_dropped():
    months = {"2026-09": 3_600, "2026-08": 3_550}        # no September 2025
    figure, _ = port_traffic.build_figure("x", "X", "X", "calls", (500, 15_000), months, TODAY)
    assert [c["basis"] for c in figure["changes"]] == ["previous month"]
    assert "No same month a year earlier comparison: MPA returned no figure for September 2025." in figure["notes"]


def test_unreadable_rows_are_counted_in_the_notes():
    rows = [{"month": "2026-09", "number_of_vessels": "11608"}, {"month": "2026-08", "number_of_vessels": "n/a"}]
    months, skipped = port_traffic.parse_arrivals(rows)
    assert months == {"2026-09": 11608} and skipped == 1
    figure, _ = port_traffic.build_figure("x", "X", "X", "arrivals", (3_000, 30_000), months, TODAY, skipped=skipped)
    assert "1 unreadable MPA row skipped." in figure["notes"]


def test_each_figure_links_its_own_dataset_and_is_flagged_preliminary():
    figs = by_id(port_traffic.fetch_port_traffic(TODAY, get=recorded()))
    assert figs["sg_vessel_arrivals"]["dataset_url"].endswith("d_d48c5a038904f6da3c603cd854b6c191/view")
    assert figs["sg_calls_bunkers"]["dataset_url"].endswith("d_48cb38d12697d3463c8cadfb22e6c61d/view")
    assert all(f["preliminary"] for f in figs.values())


def test_a_shared_url_without_a_named_source_is_refused():
    from modules.morning_brief.allowlist import SourceNotAllowed, require_allowed_url
    with pytest.raises(SourceNotAllowed, match="belongs to several sources"):
        require_allowed_url(port_traffic.API_URL)
    with pytest.raises(SourceNotAllowed, match="not on the morning-brief allowlist"):
        require_allowed_url(port_traffic.API_URL, "no_such_source")
    assert require_allowed_url(port_traffic.API_URL, "mpa_port_traffic").id == "mpa_port_traffic"


def test_the_published_brief_states_cadence_and_preliminary_for_port_calls():
    from modules.morning_brief.writer import render_brief
    from tests.test_morning_brief_payload import build
    md = render_brief(build(), {})
    part = md[md.index("### Singapore vessel arrivals and calls (MPA, monthly)"):md.index("### Ship activity")]
    assert "*Monthly (MPA publishes about three weeks after month end).*" in part
    assert "preliminary estimates" in part
