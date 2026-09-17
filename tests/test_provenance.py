"""
tests/test_provenance.py
Unit tests for modules/provenance.py's pure functions: parse_as_of and
Provenance.freshness(). Run with: python -m unittest tests.test_provenance
"""

import unittest
from datetime import datetime, timedelta, timezone

from modules.provenance import Freshness, Provenance, QualityTier, parse_as_of


class ParseAsOfTests(unittest.TestCase):
    def test_naive_datetime_assumes_utc(self):
        naive = datetime(2026, 9, 10, 12, 0, 0)
        result = parse_as_of(naive)
        self.assertEqual(result, datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc))
        self.assertIsNotNone(result.tzinfo)

    def test_aware_datetime_returned_unchanged(self):
        tz = timezone(timedelta(hours=8))
        aware = datetime(2026, 9, 10, 12, 0, 0, tzinfo=tz)
        result = parse_as_of(aware)
        self.assertEqual(result, aware)
        self.assertEqual(result.tzinfo, tz)

    def test_none_returns_none(self):
        self.assertIsNone(parse_as_of(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_as_of(""))
        self.assertIsNone(parse_as_of("   "))

    def test_nan_returns_none(self):
        self.assertIsNone(parse_as_of(float("nan")))

    def test_iso_date_string(self):
        result = parse_as_of("2026-09-10")
        self.assertEqual(result, datetime(2026, 9, 10, tzinfo=timezone.utc))

    def test_iso_month_string(self):
        result = parse_as_of("2026-09")
        self.assertEqual(result, datetime(2026, 9, 1, tzinfo=timezone.utc))

    def test_epoch_milliseconds_arcgis_style(self):
        # 2026-09-10T00:00:00Z in epoch milliseconds
        expected = datetime(2026, 9, 10, tzinfo=timezone.utc)
        epoch_ms = expected.timestamp() * 1000
        result = parse_as_of(epoch_ms)
        self.assertEqual(result, expected)

    def test_out_of_range_numeric_returns_none(self):
        self.assertIsNone(parse_as_of(10**20))

    def test_unparseable_string_returns_none(self):
        self.assertIsNone(parse_as_of("not a date"))

    def test_unparseable_never_raises(self):
        try:
            result = parse_as_of("definitely-not-a-timestamp")
        except Exception as e:  # pragma: no cover - the whole point is this never fires
            self.fail(f"parse_as_of raised {e!r} instead of returning None")
        self.assertIsNone(result)

    def test_unsupported_type_returns_none(self):
        self.assertIsNone(parse_as_of(object()))
        self.assertIsNone(parse_as_of([1, 2, 3]))


def _make_provenance(as_of, max_age):
    return Provenance(
        source_name="Test Source",
        source_url=None,
        retrieved_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        as_of=as_of,
        licence="test",
        quality_tier=QualityTier.LIVE_API,
        max_age=max_age,
    )


class FreshnessTests(unittest.TestCase):
    def test_as_of_none_is_unknown(self):
        prov = _make_provenance(as_of=None, max_age=timedelta(hours=36))
        self.assertEqual(prov.freshness(), Freshness.UNKNOWN)

    def test_max_age_none_is_unknown(self):
        prov = _make_provenance(as_of=datetime(2026, 9, 10, tzinfo=timezone.utc), max_age=None)
        self.assertEqual(prov.freshness(), Freshness.UNKNOWN)

    def test_both_missing_is_unknown(self):
        prov = _make_provenance(as_of=None, max_age=None)
        self.assertEqual(prov.freshness(), Freshness.UNKNOWN)

    def test_exactly_at_max_age_boundary_is_fresh(self):
        as_of = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)
        max_age = timedelta(hours=36)
        now = as_of + max_age  # exactly on the boundary
        prov = _make_provenance(as_of=as_of, max_age=max_age)
        self.assertEqual(prov.freshness(now=now), Freshness.FRESH)

    def test_one_second_past_boundary_is_stale(self):
        as_of = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)
        max_age = timedelta(hours=36)
        now = as_of + max_age + timedelta(seconds=1)
        prov = _make_provenance(as_of=as_of, max_age=max_age)
        self.assertEqual(prov.freshness(now=now), Freshness.STALE)

    def test_well_within_max_age_is_fresh(self):
        as_of = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)
        now = as_of + timedelta(hours=1)
        prov = _make_provenance(as_of=as_of, max_age=timedelta(hours=36))
        self.assertEqual(prov.freshness(now=now), Freshness.FRESH)


if __name__ == "__main__":
    unittest.main()
