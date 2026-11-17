"""
tests/test_timezone_independence.py

Every timestamp must become a UTC date explicitly, never via the machine's
local time. The same recorded PortWatch data, as ISO dates and as epoch ms
at 23:30 UTC (07:30 the next day in Singapore), must give identical daily
totals and as-of dates with TZ=UTC and TZ=Asia/Singapore.
"""

import json
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest import mock

import pytest

from modules import portwatch, provenance
from modules.morning_brief.activity import CHOKEPOINTS, weekly_figures
from tests.fixture_http import FIXTURES

TODAY = date(2026, 10, 12)


@contextmanager
def local_tz(name):
    old = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


def rows(name):
    return [f["attributes"] for f in json.loads((FIXTURES / f"portwatch/{name}.json").read_text())["features"]]


def totals(fixture):
    figures, excluded = weekly_figures(rows(fixture), CHOKEPOINTS, "n_total", "transits", "transits", TODAY)
    assert excluded == []
    return [(f["id"], f["value"], f["as_of"], f["changes"][0]["previous_value"]) for f in figures]


def test_tz_switch_really_changes_local_time():
    # Guards the tests below: if TZ could not be switched they would prove nothing.
    with local_tz("Asia/Singapore"):
        assert time.timezone == -8 * 3600
    with local_tz("UTC"):
        assert time.timezone == 0


@pytest.mark.parametrize("fixture", ["chokepoints_ok", "chokepoints_epoch_late_utc"])
def test_daily_totals_identical_in_singapore_and_utc(fixture):
    with local_tz("UTC"):
        in_utc = totals(fixture)
    with local_tz("Asia/Singapore"):
        in_sgt = totals(fixture)
    assert in_utc == in_sgt
    assert in_utc[0][2] == "2026-10-04"          # the UTC date, not the Singapore one


def test_epoch_and_iso_versions_agree():
    with local_tz("Asia/Singapore"):
        assert totals("chokepoints_ok") == totals("chokepoints_epoch_late_utc")


def test_offset_timestamp_uses_its_utc_date():
    # 23:51 at -04:00 is 03:51 UTC the next day.
    assert provenance.utc_date("2026-10-11T23:51:00-04:00") == date(2026, 10, 12)


def test_congestion_reason_dates_identical_in_singapore_and_utc():
    def ms(day):   # 23:30 UTC on `day`, as epoch milliseconds
        return int(datetime(2026, *day, 23, 30, tzinfo=timezone.utc).timestamp() * 1000)
    data = [{"portname": "Fujairah", "date": ms(d), "portcalls": c} for d, c in (((10, 2), 7), ((9, 20), 0))]
    with local_tz("UTC"):
        utc = portwatch._compute_congestion(data, ["Fujairah"])
    with local_tz("Asia/Singapore"):
        sgt = portwatch._compute_congestion(data, ["Fujairah"])
    assert utc == sgt
    assert "20 September 2026" in utc[1]["Fujairah"]


class _Clock(datetime):
    """20:00 UTC on 12-10-2026, already 13-10 in Singapore."""
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc).astimezone(tz) if tz else \
            datetime(2026, 10, 13, 4, 0)


def test_utc_today_and_portwatch_cutoff_ignore_local_date():
    response = mock.Mock(**{"json.return_value": {"features": []}, "raise_for_status.return_value": None})
    with local_tz("Asia/Singapore"), mock.patch.object(provenance, "datetime", _Clock), \
            mock.patch.object(portwatch.requests, "get", return_value=response) as get:
        assert provenance.utc_today() == date(2026, 10, 12)
        portwatch.fetch_port_activity()
    assert "DATE '2026-09-28'" in get.call_args.kwargs["params"]["where"]   # 12-10 minus 14 days
