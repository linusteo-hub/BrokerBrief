"""
modules/morning_brief/news.py

News items for Freight (direction in words), Sale & Purchase and Events,
built from RSS/Atom title and excerpt only. Full article pages are never
fetched.

What reaches the payload, per item:
- headline, link, publisher, author/byline, published date, section;
- for our own (non-wire) items only: an excerpt with every sentence that
  contains a digit removed, so the model has context but no figures to copy,
  and the public archive carries none (feed excerpts quote licensed indices);
- wire items (Reuters, Bloomberg, …) get headline and link only.

Items are dropped whole if the title or excerpt names a banned source, or if
a freight item's headline quotes figures (those are usually index levels).
Drop reasons never quote the offending text, so the archive stays clean.
"""

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional

import requests

from modules.morning_brief.allowlist import WIRE_AGENCIES, mentions_banned_source, require_allowed
from modules.morning_brief.figures import fmt_date
from modules.morning_brief.guarded_http import guarded_get

FEEDS = ("gcaptain", "splash247", "maritime_executive")

# How far back each section looks, and how many items it keeps (newest first).
WINDOWS = {"events": timedelta(hours=48), "freight": timedelta(days=7), "sale_and_purchase": timedelta(days=7)}
LIMITS = {"events": 8, "freight": 9, "sale_and_purchase": 6}
EXCERPT_MAX_CHARS = 400
DUPLICATE_THRESHOLD = 0.6   # title word overlap (Jaccard) above which two items are one story

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}

# Wire marks we look for beyond the author field (title, first line, credit fields).
WIRE_MARK = re.compile(r"\b(Reuters|Bloomberg)\b", re.IGNORECASE)
# "By Jan Wolfe Oct 11 (Reuters) – …": a byline counts only when a clear break
# (comma, dash, bracket, digit or month) follows, else names run into the text.
_NAME = r"[A-Z][\w.'’-]+"
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
BYLINE = re.compile(rf"^\s*By\s+({_NAME}(?:\s+(?:and\s+)?{_NAME}){{0,5}}?)\s*(?=[,–—(|-]|\d|{_MONTH}\s)")

SNP = re.compile(r"\b(sold|sells?|sale|buys?|bought|buyers?|acquires?|acquisition|snap(s|ped)? up|en bloc|"
                 r"resales?|newbuild(ing)?s?|orders?|ordered|ordering|contracts? for|recycling|"
                 r"demolition|scrapp(ed|ing))\b", re.IGNORECASE)
SHIP = re.compile(r"\b(vessels?|ships?|carriers?|newbuild(ing)?s?|resales?|en bloc|recycling|demolition|"
                  r"gas carriers?|lngcs?|lpgcs?|vlgcs?|car carriers?|pctcs?)\b", re.IGNORECASE)
# Rate wording only: bare "freight" also names companies ("… Freight Company").
FREIGHT = re.compile(r"\b(rates?|freight (market|rates?)|earnings|spot market|fixtures?|time[- ]charter|"
                     r"charter market|tce)\b", re.IGNORECASE)
SEGMENTS = (
    ("dry_bulk", re.compile(r"\b(capesizes?|panamaxes|panamax|kamsarmaxe?s?|supramaxe?s?|ultramaxe?s?|"
                            r"handysizes?|bulkers?|bulk carriers?|dry bulk|dry cargo)\b", re.I)),
    ("tanker", re.compile(r"\b(vlccs?|suezmaxe?s?|aframaxe?s?|lr[12]s?|mr tankers?|tankers?)\b", re.I)),
    ("container", re.compile(r"\b(containers?|containerships?|boxships?|teu|liners?|box rates)\b", re.I)),
)


class FeedError(Exception):
    pass


# ── Parsing ──────────────────────────────────────────────────────────────────

def _text(element) -> str:
    return "" if element is None else "".join(element.itertext()).strip()


def strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)          # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value)      # Atom: ISO 8601
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_feed(content: bytes) -> list[dict]:
    """RSS 2.0 or Atom bytes -> raw entries. Raises FeedError if unparseable."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise FeedError(f"feed is not valid XML ({e})") from None

    entries = []
    if root.tag == "rss":
        for item in root.findall("./channel/item"):
            entries.append({
                "title": _text(item.find("title")),
                "link": _text(item.find("link")),
                "author": _text(item.find("dc:creator", NS)) or _text(item.find("author")),
                "published": _parse_date(_text(item.find("pubDate"))),
                "categories": [_text(c) for c in item.findall("category")],
                "excerpt_html": _text(item.find("description")),
                "credit_fields": [_text(e) for e in (item.find("source"), item.find("dc:rights", NS),
                                                     item.find("media:credit", NS)) if e is not None],
            })
    elif root.tag == f"{{{NS['atom']}}}feed":
        for entry in root.findall("atom:entry", NS):
            # Elements without children are falsy, so no `or` between finds.
            link = entry.find("atom:link[@rel='alternate']", NS)
            if link is None:
                link = entry.find("atom:link", NS)
            entries.append({
                "title": _text(entry.find("atom:title", NS)),
                "link": link.get("href", "") if link is not None else "",
                "author": _text(entry.find("atom:author/atom:name", NS)),
                "published": _parse_date(_text(entry.find("atom:published", NS))
                                         or _text(entry.find("atom:updated", NS))),
                "categories": [c.get("term", "") for c in entry.findall("atom:category", NS)],
                "excerpt_html": _text(entry.find("atom:summary", NS)),
                "credit_fields": [_text(e) for e in (entry.find("atom:source", NS), entry.find("atom:rights", NS))
                                  if e is not None],
            })
    else:
        raise FeedError(f"unrecognised feed format (root element {root.tag!r})")
    return entries


# ── Rules ────────────────────────────────────────────────────────────────────

def wire_agency(entry: dict, excerpt: str) -> Optional[str]:
    """The news agency if this is a wire story, else None.

    Checked in order: the author field (any agency in WIRE_AGENCIES), then
    "Reuters"/"Bloomberg" in the title, the excerpt's first line (where the
    dateline sits) or any source/credit field. An author field is not enough
    on its own: some publishers post wire copy under a staff name or none.
    """
    author = (entry.get("author") or "").strip()
    for agency in WIRE_AGENCIES:
        if author.lower() == agency.lower():
            return agency
    first_line = excerpt.split("\n", 1)[0][:200]
    for text in [entry.get("title", ""), first_line, *entry.get("credit_fields", [])]:
        match = WIRE_MARK.search(text or "")
        if match:
            return match.group(1).title()
    return None


def digit_free_excerpt(excerpt: str) -> Optional[str]:
    """Drop every sentence containing a digit; None if nothing usable is left."""
    sentences = re.split(r"(?<=[.!?…])\s+", excerpt)
    kept = [s for s in sentences if s and not re.search(r"\d", s)]
    text = " ".join(kept).strip()
    if len(text) > EXCERPT_MAX_CHARS:
        text = text[:EXCERPT_MAX_CHARS].rsplit(" ", 1)[0] + " …"
    return text if len(text) >= 40 else None


def segment_of(title: str, categories: list) -> Optional[str]:
    """Segment from the headline; feed categories only break a tie when the
    headline names no segment and exactly one category does (multi-topic
    stories carry several categories and would otherwise be mislabelled)."""
    for name, pattern in SEGMENTS:
        if pattern.search(title):
            return name
    from_categories = {name for name, pattern in SEGMENTS for c in categories if pattern.search(c)}
    return from_categories.pop() if len(from_categories) == 1 else None


def classify(title: str, categories: list) -> tuple[str, Optional[str]]:
    """-> (section, segment). S&P needs a deal word *and* a merchant ship
    (a segment word, generic vessel word, or a newbuilding/recycling word);
    company takeovers and naval orders are events."""
    segment = segment_of(title, categories)
    if SNP.search(title) and (any(p.search(title) for _, p in SEGMENTS) or SHIP.search(title)):
        return "sale_and_purchase", segment
    if FREIGHT.search(title):
        return "freight", segment
    return "events", None


def _title_words(title: str) -> set:
    words = re.findall(r"[a-z]+", title.lower())
    return {w for w in words if len(w) > 3}


def is_duplicate(a: str, b: str) -> bool:
    wa, wb = _title_words(a), _title_words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= DUPLICATE_THRESHOLD


# ── Building items ───────────────────────────────────────────────────────────

def build_item(entry: dict, source_id: str, now: datetime) -> tuple[Optional[dict], Optional[str]]:
    """-> (item, None) or (None, reason it was dropped)."""
    source = require_allowed(source_id)
    title = strip_html(entry.get("title", ""))
    link = entry.get("link", "").strip()
    if not title or not link.startswith("https://"):
        return None, "missing headline or https link"
    excerpt = strip_html(entry.get("excerpt_html", ""))
    if mentions_banned_source(title) or mentions_banned_source(excerpt):
        return None, "names a banned source"
    published = entry.get("published")
    if published is None:
        return None, "no publication date"

    section, segment = classify(title, entry.get("categories", []))
    if now - published > WINDOWS[section] or published - now > timedelta(hours=1):
        return None, "outside the time window"
    if section == "freight" and re.search(r"\d", title):
        return None, "freight headline quotes figures"

    agency = wire_agency(entry, excerpt)
    byline = BYLINE.match(excerpt)
    author = entry.get("author", "").strip()
    if agency or author.lower() == source.publisher.lower():
        author = ""          # an agency or the house name is not a person's byline
    summary_text = None if agency else digit_free_excerpt(excerpt)

    return {
        "id": hashlib.sha1(link.encode()).hexdigest()[:12],
        "headline": title,
        "link": link,
        "source_id": source_id,
        "publisher": source.name,
        "author": byline.group(1) if byline else (author or None),
        "wire_agency": agency,
        "summary_allowed": summary_text is not None,
        "excerpt": summary_text,
        "published": published.astimezone(timezone.utc).isoformat(),
        "published_display": fmt_date(published.astimezone(timezone.utc).date()),
        "section": section,
        "segment": segment,
        "also_reported_by": [],
    }, None


def select_items(items: list[dict]) -> dict:
    """Deduplicate across feeds (keeping the earliest report), then keep the
    newest LIMITS[section] per section."""
    kept: list[dict] = []
    for item in sorted(items, key=lambda i: i["published"]):
        original = next((k for k in kept if k["link"] == item["link"]
                         or is_duplicate(k["headline"], item["headline"])), None)
        if original:
            if item["publisher"] not in original["also_reported_by"] + [original["publisher"]]:
                original["also_reported_by"].append(item["publisher"])
        else:
            kept.append(item)
    by_section = {section: [] for section in LIMITS}
    for item in sorted(kept, key=lambda i: i["published"], reverse=True):
        if len(by_section[item["section"]]) < LIMITS[item["section"]]:
            by_section[item["section"]].append(item)
    return by_section


def fetch_news(now: datetime, get: Callable = guarded_get) -> dict:
    """Returns {"sections": {section: [items]}, "dropped": [...], "feed_errors": {source_id: reason}}."""
    items, dropped, feed_errors = [], [], {}
    for source_id in FEEDS:
        source = require_allowed(source_id)
        try:
            response = get(source.fetch_urls[0], timeout=20)
            response.raise_for_status()
            entries = parse_feed(response.content)
        except (requests.RequestException, FeedError) as e:
            feed_errors[source_id] = str(e)
            continue
        if not entries:
            feed_errors[source_id] = "feed contained no items"
            continue
        for entry in entries:
            item, reason = build_item(entry, source_id, now)
            if item:
                items.append(item)
            elif reason != "outside the time window":
                link = entry.get("link", "")
                dropped.append({
                    "source_id": source_id,
                    "id": hashlib.sha1(link.encode()).hexdigest()[:12],
                    # A banned item's URL slug can carry the banned name; keep only its hash.
                    "link": None if reason == "names a banned source" else link,
                    "reason": reason,
                })
    return {"sections": select_items(items), "dropped": dropped, "feed_errors": feed_errors}
