"""
modules/provenance.py

Single provenance representation shared by every market-data source (EIA,
PortWatch, the manual/CSV bunker pipeline, and any future feed).

Principle: a value's freshness is a property of the DATA (as_of), not of
when we happened to fetch it (retrieved_at). A week-old number fetched a
second ago is stale, not live.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Protocol


# Source name and licence label for invented demo rows (modules/data.py).
# Anything carrying this label is not real data and must never reach
# Market Intelligence or the morning brief.
SAMPLE_LABEL = "SAMPLE — not real data"


class QualityTier(str, Enum):
    LIVE_API = "LIVE_API"  # fetched live from an authoritative API/feed
    MANUAL_ENTRY = "MANUAL_ENTRY"  # analyst-entered CSV/sample row
    USER_OVERRIDE = "USER_OVERRIDE"  # typed into the UI for this session


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"  # as_of is missing/unparseable, or max_age is None


def parse_as_of(value) -> Optional[datetime]:
    """
    The only sanctioned way to build the `as_of` field from source data.
    Never raises — anything that can't be confidently parsed becomes None,
    so a malformed upstream/CSV value degrades to Freshness.UNKNOWN rather
    than crashing the page.
    """
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        try:
            year, month = text.split("-")[:2]
            return datetime(int(year), int(month), 1, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            return None

    return None


@dataclass(frozen=True)
class Provenance:
    source_name: str
    source_url: Optional[str]
    retrieved_at: datetime  # when WE fetched/assembled this value — audit only,
    # never read by freshness(). Always tz-aware UTC.
    as_of: Optional[datetime]  # the observation date the SOURCE reports for this
    # value. This is what freshness() judges. None means
    # the source gave us no such date. Build this only
    # via parse_as_of() — freshness() assumes it is
    # already None or tz-aware.
    licence: str
    quality_tier: QualityTier
    max_age: Optional[timedelta]  # declared per source; None = never judged

    def freshness(self, now: Optional[datetime] = None) -> Freshness:
        if self.as_of is None or self.max_age is None:
            return Freshness.UNKNOWN
        now = now or datetime.now(timezone.utc)
        age = now - self.as_of
        return Freshness.FRESH if age <= self.max_age else Freshness.STALE


class Source(Protocol):
    """Declarative metadata contract implemented by every live-fetch source
    (EIA spot, EIA forecast, PortWatch, future news feeds)."""

    name: str
    url: Optional[str]
    licence: str
    quality_tier: QualityTier
    max_age: Optional[timedelta]


@dataclass(frozen=True)
class SourceInfo:
    """The one concrete implementation of Source — every live source is an
    instance of this, not a subclass."""

    name: str
    url: Optional[str]
    licence: str
    quality_tier: QualityTier
    max_age: Optional[timedelta]


def stamp(source: Source, *, as_of: Optional[datetime], retrieved_at: Optional[datetime] = None) -> Provenance:
    """The one function every fetch path calls to produce a Provenance.
    `as_of` is a required keyword (though it may be None) so a caller cannot
    forget to think about it."""
    return Provenance(
        source_name=source.name,
        source_url=source.url,
        licence=source.licence,
        quality_tier=source.quality_tier,
        max_age=source.max_age,
        as_of=as_of,
        retrieved_at=retrieved_at or datetime.now(timezone.utc),
    )


# ── Publication cadence and staleness limits ─────────────────────────────────
# EIA_SPOT_MAX_AGE was checked against EIA's spot-price table (Phase 0 source
# audit, 12-10-2026, docs/morning-brief-build-plan.md): daily values are
# released weekly (e.g. release 07-10-2026 held data to 06-10), so the newest
# value can be ~9 days old. It is the single EIA spot limit for both the app
# and the morning brief (Linus, 12-10-2026).
EIA_SPOT_MAX_AGE = timedelta(days=10)

# The limits below are still UNVERIFIED guesses based on marketing pages or the
# app's old UI copy, not on each source's documented update schedule. Check
# them against the source's real docs before relying on them beyond a demo.
EIA_FORECAST_MAX_AGE = timedelta(days=35)  # assumes STEO forecast is republished ~monthly;
# not checked. EIA forecast currently has no as_of at
# all (see modules/eia.py), so this max_age is presently
# inert — freshness() always returns UNKNOWN for it.
PORTWATCH_MAX_AGE = timedelta(days=10)  # assumes weekly (Tuesday) cadence, per app.py's
# existing (also unverified) UI caption, plus slack;
# not checked against PortWatch's own documentation
MANUAL_ENTRY_MAX_AGE = timedelta(hours=48)  # arbitrary placeholder — no analyst refresh SLA
# exists today; needs an actual policy decision, this
# is not derived from anything
