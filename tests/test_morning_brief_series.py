"""
tests/test_morning_brief_series.py

The chart history ("series") carried by price and bunker-sales figures. Every
point carries its own display strings, the newest point is the figure itself,
a point outside the plausible range drops the whole series with the reason,
and the publishing gate re-checks every point.
"""

import copy
import json
from datetime import date

import pytest

from modules.morning_brief import bunker_sales
from modules.morning_brief.figures import fmt_date, make_series, money
from modules.morning_brief.payload import final_gate
from tests.fixture_http import FIXTURES
from tests.test_morning_brief_payload import build

FMT = money("USD/bbl", 2)


def test_series_points_carry_display_strings():
    series, note = make_series([(date(2026, 10, 5), 80.0), (date(2026, 10, 6), 81.5)], FMT, label="L",
                               date_display=fmt_date, plausible_range=(10, 300))
    assert note is None
    assert series["points"][-1] == {"date": "2026-10-06", "date_display": "6 October 2026",
                                    "value": 81.5, "display": "USD 81.50/bbl"}


def test_one_point_out_of_range_drops_the_series_with_the_reason():
    series, note = make_series([(date(2026, 10, 5), 5.0), (date(2026, 10, 6), 81.5)], FMT, label="L",
                               date_display=fmt_date, plausible_range=(10, 300))
    assert series is None
    assert "USD 5.00/bbl on 5 October 2026 is outside the plausible range" in note


def test_a_single_point_is_not_a_chart():
    series, note = make_series([(date(2026, 10, 6), 81.5)], FMT, label="L", date_display=fmt_date,
                               plausible_range=None)
    assert series is None and "fewer than two" in note


def test_newest_point_is_the_figure_and_points_run_oldest_first():
    payload = build()
    figures = payload["sections"]["prices"]["items"] + payload["sections"]["bunker_sales"]["items"]
    assert figures
    for fig in figures:
        points = fig["series"]["points"]
        assert points[-1]["value"] == fig["value"] and points[-1]["display"] == fig["display"]
        assert [p["date"] for p in points] == sorted(p["date"] for p in points)


def test_price_chart_covers_at_most_nine_weeks():
    for fig in build()["sections"]["prices"]["items"]:
        first, last = (date.fromisoformat(fig["series"]["points"][i]["date"]) for i in (0, -1))
        assert (last - first).days < 63


def test_bunker_chart_is_thirteen_months_and_stops_at_an_incomplete_month():
    records = json.loads((FIXTURES / "mpa/bunker_sales_ok.json").read_text())["result"]["records"]
    months = bunker_sales.parse_records(records)
    figures, _ = bunker_sales.build_figures(copy.deepcopy(months), date(2026, 10, 25))
    assert len(figures[0]["series"]["points"]) == 13
    # Remove one fuel type from the month four back: the chart keeps only the three newer months and the latest.
    gap = bunker_sales.shift_month(max(months), -4)
    months[gap].pop("LNG")
    figures, _ = bunker_sales.build_figures(months, date(2026, 10, 25))
    assert len(figures[0]["series"]["points"]) == 4
    assert all(p["date"] > bunker_sales.month_end(gap).isoformat() for p in figures[0]["series"]["points"])


def test_gate_refuses_a_chart_point_outside_the_range():
    payload = build()
    payload["sections"]["prices"]["items"][0]["series"]["points"][0]["value"] = 999.0
    with pytest.raises(ValueError, match="chart point outside"):
        final_gate(payload)


def test_gate_refuses_a_chart_point_without_display():
    payload = build()
    payload["sections"]["bunker_sales"]["items"][0]["series"]["points"][0]["display"] = ""
    with pytest.raises(ValueError, match="without a value and display"):
        final_gate(payload)
