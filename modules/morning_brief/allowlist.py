"""
modules/morning_brief/allowlist.py

The only sources the morning brief may use, with the terms each was accepted
under (Phase 0 source audit, 12-10-2026 — see docs/morning-brief-build-plan.md).

This is the single place in deployed code that names banned sources: the
denylist and the banned-name pattern below. Everything else imports them.

Two kinds of source:
- "data": numeric series (EIA, PortWatch). Numbers may be republished only if
  `redistributable` is True.
- "news": RSS feeds. `redistributable` is False — we never republish their
  text. We use the headline, the link, the credit and our own digit-free
  summary; wire items (Reuters, Bloomberg, …) get headline and link only.
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional


class SourceNotAllowed(Exception):
    """Raised when the payload builder is handed a source it may not use."""


@dataclass(frozen=True)
class AllowedSource:
    id: str
    name: str
    publisher: str
    url: str
    terms_url: str
    licence: str            # the terms we accepted, in our words
    redistributable: bool   # may numbers from this source appear in the public brief?
    kind: str               # "data" or "news"
    credit: str             # credit line to print under Sources
    quality_tier: str       # LIVE_API for data; NEWS_EXCERPT for feeds
    max_age: Optional[timedelta]  # staleness threshold for this source's data
    fetch_urls: tuple = ()  # URL prefixes our code may request for this source
    notes: str = ""


ALLOWLIST: dict[str, AllowedSource] = {
    "eia_spot": AllowedSource(
        id="eia_spot",
        name="EIA spot prices",
        publisher="U.S. Energy Information Administration",
        url="https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm",
        terms_url="https://www.eia.gov/about/copyrights_reuse.php",
        licence="Public domain (U.S. Government work); credit requested",
        redistributable=True,
        kind="data",
        credit="Source: U.S. Energy Information Administration, spot prices",
        quality_tier="LIVE_API",
        # Daily values released weekly, so the newest value can be ~9 days old.
        max_age=timedelta(days=10),
        fetch_urls=("https://api.eia.gov/v2/petroleum/pri/spt/data/",),
        notes=("EIA's spot prices come from Refinitiv (LSEG). EIA puts no restriction "
               "on these tables and FRED tags them public domain, citation requested."),
    ),
    "imf_portwatch": AllowedSource(
        id="imf_portwatch",
        name="IMF PortWatch",
        publisher="International Monetary Fund",
        url="https://portwatch.imf.org",
        terms_url="https://www.imf.org/en/about/copyright-and-terms",
        licence="IMF terms: reuse and publication with credit; commercial reuse and "
                "automated bulk download need IMF permission",
        redistributable=True,
        kind="data",
        credit=("BrokerBrief calculations based on data from International Monetary Fund, "
                "PortWatch, https://portwatch.imf.org"),
        quality_tier="LIVE_API",
        # Weekly batches lagging 8–10 days; 14 days allows one late batch.
        max_age=timedelta(days=14),
        fetch_urls=("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query",
                    "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"),
        notes="Physical activity (transits, port calls), not freight rates. "
              "Keep queries small and once per run (no bulk download).",
    ),
    "gcaptain": AllowedSource(
        id="gcaptain",
        name="gCaptain",
        publisher="gCaptain",
        url="https://gcaptain.com/feed/",
        terms_url="https://gcaptain.com/editorial-standards/",
        licence="No terms of use published; default copyright. Headline, link and own summary only.",
        redistributable=False,
        kind="news",
        credit="gCaptain (https://gcaptain.com)",
        quality_tier="NEWS_EXCERPT",
        max_age=None,
        fetch_urls=("https://gcaptain.com/feed/",),
        notes="Carries Reuters and Bloomberg wire stories: headline and link only.",
    ),
    "splash247": AllowedSource(
        id="splash247",
        name="Splash247",
        publisher="Splash Maritime Group",
        url="https://splash247.com/feed/",
        terms_url="https://splash247.com/terms-of-service/",
        licence="Terms pages empty; all rights reserved. Headline, link and own summary only.",
        redistributable=False,
        kind="news",
        credit="Splash247 (https://splash247.com)",
        quality_tier="NEWS_EXCERPT",
        max_age=None,
        fetch_urls=("https://splash247.com/feed/",),
        notes="Blocked one fetcher with HTTP 403; test from GitHub Actions before Phase 3.",
    ),
    "maritime_executive": AllowedSource(
        id="maritime_executive",
        name="The Maritime Executive",
        publisher="The Maritime Executive",
        url="https://maritime-executive.com/articles.rss",
        terms_url="https://maritime-executive.com/privacy-policy",
        licence="No terms page; all rights reserved. Headline, link and own summary only.",
        redistributable=False,
        kind="news",
        credit="The Maritime Executive (https://maritime-executive.com)",
        quality_tier="NEWS_EXCERPT",
        max_age=None,
        fetch_urls=("https://maritime-executive.com/articles.rss",),
        notes="Atom feed with many press releases.",
    ),
}


# Sources that were considered and refused, with the reason. Not exhaustive —
# anything absent from ALLOWLIST is refused anyway — but naming them gives a
# clearer error and documents the decision.
DENYLIST: dict[str, str] = {
    "baltic_exchange": "Baltic Exchange data policy forbids public display, including index levels quoted in the media.",
    "freightos_fbx": "FBX is Baltic Exchange container data (Freightos is its authorised firm).",
    "worldscale": "Worldscale flat rates are subscriber-only; WS points in news are usually Baltic assessments.",
    "clarksons": "Clarksons Research is under academic terms prohibiting systematic extraction; offline calibration only.",
    "lloyds_list": "Lloyd's List is under academic terms prohibiting systematic extraction; offline calibration only.",
    "platts": "Licensed price assessments.",
    "argus": "Licensed price assessments.",
    "ice": "ICE exchange prices (e.g. ICE Gasoil) are licensed exchange data.",
    "hellenic_shipping_news": "Disclaimer prohibits republication or paraphrase without written authorisation.",
    "the_loadstar": "Terms forbid use in AI systems or LLM ingestion.",
    "drewry_wci": "Drewry terms forbid republishing; personal, internal use only.",
    "scfi": "No reuse terms found; all rights reserved; login-walled.",
}


# News items whose title or excerpt names a banned source are dropped whole:
# their wording usually relays that source's index ("the BDI fell"), and the
# public archive must not carry these names (verify skill, step 4).
# "Baltic" alone is not matched — it is also a sea.
BANNED_NAME_PATTERN = re.compile(
    r"baltic\s+exchange|baltic\s+(dry|capesize|panamax|supramax|handysize|clean|dirty)"
    r"|baltic\s+index|\bBDI\b|\bBDTI\b|\bBCTI\b|\bBCI\b|\bBPI\b|\bBSI\b|\bFBX\b|freightos"
    r"|worldscale|\bWS\s?\d|clarksons|clarksea|lloyd[’']?s\s+list|platts|\bargus\b"
    r"|\bICE\s+(gasoil|brent|futures)",
    re.IGNORECASE,
)

# Feed authors (or excerpt datelines) marking a news-agency wire story.
WIRE_AGENCIES = ("Reuters", "Bloomberg", "Associated Press", "AP", "AFP", "Agence France-Presse")


def mentions_banned_source(text: str) -> Optional[str]:
    """Return the first banned-source mention in `text`, or None."""
    match = BANNED_NAME_PATTERN.search(text or "")
    return match.group(0) if match else None


def require_allowed_url(url: str) -> AllowedSource:
    """Every HTTP request the brief makes passes through this. A URL that is not
    one of an allowlisted source's `fetch_urls` raises SourceNotAllowed — it is
    never caught by the fetchers, so the run fails loudly."""
    for source in ALLOWLIST.values():
        for prefix in source.fetch_urls:
            # Exact URL, or the prefix followed by a query string only.
            if url == prefix or url.startswith(prefix + "?"):
                return source
    raise SourceNotAllowed(f"refusing to fetch {url!r}: not an allowlisted URL")


def require_allowed(source_id: str, *, numeric: bool = False) -> AllowedSource:
    """The gate every payload entry passes through.

    Refuses a source that is denylisted or simply not on the allowlist, and
    refuses numbers from a source whose numbers we may not republish.
    """
    if source_id in DENYLIST:
        raise SourceNotAllowed(f"{source_id!r} is denylisted: {DENYLIST[source_id]}")
    source = ALLOWLIST.get(source_id)
    if source is None:
        raise SourceNotAllowed(f"{source_id!r} is not on the morning-brief allowlist")
    if numeric and not source.redistributable:
        raise SourceNotAllowed(f"{source_id!r} is not redistributable, so its numbers cannot be published")
    return source
