"""
modules/morning_brief/payload.py

Assembles the morning-brief payload from the three fetchers' results. The
writer model (Phase 2) only ever sees this JSON.

Section status:
- "ok"           at least one checked item;
- "missing"      a feed failed or every value failed its checks today (reason given);
- "not_covered"  no clean source exists (container rate numbers).

Before returning, final_gate() re-checks the whole payload and raises rather
than quietly dropping anything: an item from a non-allowlisted source, a
banned name, or a digit in a news excerpt can only get here through a bug.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from modules.morning_brief.activity import fetch_activity
from modules.morning_brief.allowlist import SourceNotAllowed, mentions_banned_source, require_allowed
from modules.morning_brief.figures import fmt_date
from modules.morning_brief.news import FEEDS, fetch_news
from modules.morning_brief.prices import fetch_prices

SCHEMA_VERSION = 1
SGT = timezone(timedelta(hours=8))   # the brief is dated for Singapore readers
TRIAL_NOTICE = "Trial — under review"

CONTAINER_RATES_NOT_COVERED = (
    "No container freight index can be republished: Drewry's terms forbid republishing the WCI, "
    "the SCFI has no reuse terms, and the other indices are licensed."
)


def _section(title: str, cadence: str, items: list, failure: Optional[str]) -> dict:
    if items:
        return {"title": title, "status": "ok", "reason": None, "cadence": cadence, "items": items}
    return {"title": title, "status": "missing", "reason": failure, "cadence": cadence, "items": []}


def _failure_reason(result: dict, empty_reason: str) -> str:
    """Why a fetcher produced no items: feed error, else exclusion reasons."""
    if result.get("error"):
        return result["error"]
    reasons = sorted({e["reason"] for e in result.get("excluded", [])})
    return "; ".join(reasons) if reasons else empty_reason


def _news_failure(news: dict, label: str) -> str:
    if len(news["feed_errors"]) == len(FEEDS):
        return "every news feed failed: " + "; ".join(f"{k}: {v}" for k, v in news["feed_errors"].items())
    return f"no {label} stories met the rules in the time window"


def build_payload(*, now: datetime, prices: dict, activity: dict, news: dict) -> dict:
    """Pure assembly from fetcher results (no network); see fetch_and_build()."""
    news_sections = news["sections"]
    freight_news = news_sections["freight"]
    subsections = {
        "container_rates": {"title": "Container freight rates", "status": "not_covered",
                            "reason": CONTAINER_RATES_NOT_COVERED, "cadence": "weekly", "items": []},
        "rate_direction": _section("Freight rate direction (from news, no figures)", "weekly", freight_news,
                                   _news_failure(news, "freight-rate")),
        "activity": _section("Ship activity (transits and port calls, not rates)", "weekly", activity["items"],
                             _failure_reason(activity, "PortWatch returned no figures")),
    }
    covered = [s for s in subsections.values() if s["status"] != "not_covered"]
    freight_ok = any(s["status"] == "ok" for s in covered)
    freight = {
        "title": "Freight",
        "status": "ok" if freight_ok else "missing",
        "reason": None if freight_ok else "no freight subsection has verified content today",
        "cadence": "weekly",
        "subsections": subsections,
    }

    sections = {
        "prices": _section("Prices", "latest available (EIA releases weekly)", prices["items"],
                           _failure_reason(prices, "EIA returned no figures")),
        "freight": freight,
        "sale_and_purchase": _section("Sale & Purchase", "weekly", news_sections["sale_and_purchase"],
                                      _news_failure(news, "sale and purchase")),
        "events": _section("Events and why they matter", "daily", news_sections["events"],
                           _news_failure(news, "event")),
    }

    payload = {
        "schema_version": SCHEMA_VERSION,
        "brief_date": now.astimezone(SGT).date().isoformat(),
        "brief_date_display": fmt_date(now.astimezone(SGT).date()),
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "trial_notice": TRIAL_NOTICE,
        "sources": [],
        "sections": sections,
        "validation": {
            "excluded_figures": prices.get("excluded", []) + activity.get("excluded", []),
            "dropped_news": news.get("dropped", []),
            "feed_errors": {**({"eia_spot": prices["error"]} if prices.get("error") else {}),
                            **({"imf_portwatch": activity["error"]} if activity.get("error") else {}),
                            **news.get("feed_errors", {})},
        },
    }
    _tag_sources(payload)
    final_gate(payload)
    return payload


def iter_items(payload: dict):
    """Every item in the payload, with whether it is a numeric figure."""
    for section in payload["sections"].values():
        for sub in section.get("subsections", {"_": section}).values():
            for item in sub["items"]:
                yield item, "display" in item


def _tag_sources(payload: dict) -> None:
    """Give each source used a tag (S1, S2, …) in order of first use, record
    it in `sources`, and stamp the tag on every item."""
    tags: dict[str, str] = {}
    for item, is_figure in iter_items(payload):
        source = require_allowed(item["source_id"], numeric=is_figure)
        if source.id not in tags:
            tags[source.id] = f"S{len(tags) + 1}"
            payload["sources"].append({
                "tag": tags[source.id], "id": source.id, "name": source.name, "publisher": source.publisher,
                "url": source.url, "terms_url": source.terms_url, "licence": source.licence,
                "credit": source.credit, "redistributable": source.redistributable, "kind": source.kind,
            })
        item["source_tag"] = tags[source.id]


def final_gate(payload: dict) -> None:
    """Raise if anything in the payload breaks the data rules."""
    tags = {s["tag"] for s in payload["sources"]}
    for item, is_figure in iter_items(payload):
        require_allowed(item["source_id"], numeric=is_figure)
        if item.get("source_tag") not in tags:
            raise SourceNotAllowed(f"item {item.get('id')!r} has no source tag in `sources`")
        if not is_figure:
            if item.get("excerpt") and re.search(r"\d", item["excerpt"]):
                raise ValueError(f"news item {item['id']!r} has a digit in its excerpt")
            if item.get("wire_agency") and (item.get("excerpt") or item.get("summary_allowed")):
                raise ValueError(f"wire item {item['id']!r} must be headline and link only")
    banned = mentions_banned_source(json.dumps(payload, ensure_ascii=False))
    if banned:
        raise SourceNotAllowed("payload names a banned source; refusing to build it")


def fetch_and_build(now: Optional[datetime] = None, eia_api_key: Optional[str] = None, get=None) -> dict:
    """Run every fetcher and build the payload. `get` overrides the HTTP
    getter for all fetchers (tests); by default each uses guarded_get."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date()
    kwargs = {"get": get} if get else {}
    return build_payload(
        now=now,
        prices=fetch_prices(eia_api_key, today, **kwargs),
        activity=fetch_activity(today, **kwargs),
        news=fetch_news(now, **kwargs),
    )
