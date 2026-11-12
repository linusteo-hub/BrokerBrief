"""
tests/test_morning_brief_news.py

News fetcher, run on fixture feeds through a stand-in getter — no network.
*_sanitised.xml keep the recorded feeds' structure and metadata (12-10-2026)
with excerpts replaced by placeholder text; the other fixtures are hand-made.
"""

import re
from datetime import datetime, timezone

import pytest

from modules.morning_brief.news import FEEDS, digit_free_excerpt, fetch_news, parse_feed
from tests.fixture_http import FIXTURES, serve_by

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
RECORDED = {"gcaptain.com": "news/gcaptain_sanitised.xml", "splash247.com": "news/splash_sanitised.xml",
            "maritime-executive.com": "news/marex_sanitised.xml"}


def feeds(**overrides):
    """A getter serving one fixture per feed host; overrides map host -> (fixture[, status])."""
    def choose(url, params):
        host = re.match(r"https://([^/]+)/", url).group(1)
        chosen = overrides.get(host, RECORDED[host])
        return chosen if isinstance(chosen, tuple) else (chosen,)
    return serve_by(choose)


def all_items(result):
    return [item for items in result["sections"].values() for item in items]


def by_link(result):
    return {item["link"]: item for item in all_items(result)}


# ── Recorded structure ───────────────────────────────────────────────────────

def test_recorded_feeds_parse_in_both_formats():
    for name in ("gcaptain_sanitised", "splash_sanitised", "marex_sanitised"):
        entries = parse_feed((FIXTURES / f"news/{name}.xml").read_bytes())
        assert entries and all(e["title"] and e["link"].startswith("https://") and e["published"] for e in entries)


def test_recorded_feeds_build_items_with_credit():
    result = fetch_news(NOW, get=feeds())
    assert result["feed_errors"] == {}
    items = all_items(result)
    assert {i["publisher"] for i in items} == {"gCaptain", "Splash247", "The Maritime Executive"}
    splash = next(i for i in items if i["headline"] == "Chinese buyers snap up capesizes")
    assert (splash["section"], splash["segment"], splash["author"]) == ("sale_and_purchase", "dry_bulk", "Hans Thaulow")


def test_feed_author_marks_wire_items_link_only():
    items = all_items(fetch_news(NOW, get=feeds()))
    bloomberg = next(i for i in items if i["headline"].startswith("Saudi Eyes"))
    assert bloomberg["wire_agency"] == "Bloomberg"
    assert bloomberg["summary_allowed"] is False and bloomberg["excerpt"] is None


def test_house_name_is_not_a_byline():
    items = all_items(fetch_news(NOW, get=feeds()))
    assert all(i["author"] != "The Maritime Executive" for i in items)


# ── Wire rule beyond the author field ────────────────────────────────────────

@pytest.fixture
def special():
    return by_link(fetch_news(NOW, get=feeds(**{"gcaptain.com": "news/special_cases.xml"})))


def test_reuters_item_without_author_is_detected_from_dateline(special):
    item = special["https://gcaptain.com/test-reuters-no-author/"]
    assert item["wire_agency"] == "Reuters" and item["excerpt"] is None and not item["summary_allowed"]


def test_bloomberg_in_title_is_wire(special):
    assert special["https://gcaptain.com/test-bloomberg-in-title/"]["wire_agency"] == "Bloomberg"


def test_reuters_in_credit_field_is_wire(special):
    assert special["https://gcaptain.com/test-reuters-credit-field/"]["wire_agency"] == "Reuters"


# ── Digits, figures and other drops ──────────────────────────────────────────

def test_sentences_with_digits_are_removed_from_excerpt(special):
    item = special["https://gcaptain.com/test-mixed-digits/"]
    assert item["summary_allowed"]
    assert not re.search(r"\d", item["excerpt"])
    assert "Brokers expect activity to stay brisk" in item["excerpt"]
    assert item["author"] == "Jane Example and Sam Writer"   # byline named in the excerpt


def test_excerpt_with_only_figures_gives_headline_and_link_only(special):
    item = special["https://gcaptain.com/test-all-digits/"]
    assert item["summary_allowed"] is False and item["excerpt"] is None


def test_no_excerpt_anywhere_contains_a_digit():
    result = fetch_news(NOW, get=feeds(**{"gcaptain.com": "news/special_cases.xml"}))
    assert all(not re.search(r"\d", i["excerpt"] or "") for i in all_items(result))


def test_freight_direction_story_is_kept(special):
    item = special["https://gcaptain.com/test-freight-direction/"]
    assert (item["section"], item["segment"]) == ("freight", "dry_bulk")


def test_freight_headline_with_figures_is_dropped():
    result = fetch_news(NOW, get=feeds(**{"gcaptain.com": "news/special_cases.xml"}))
    reasons = {d["link"]: d["reason"] for d in result["dropped"]}
    assert reasons["https://gcaptain.com/test-freight-headline-digits/"] == "freight headline quotes figures"
    assert reasons["https://gcaptain.com/test-no-date/"] == "no publication date"
    assert "https://gcaptain.com/test-old/" not in by_link(result)


def test_items_naming_banned_sources_are_dropped_without_quoting_them():
    result = fetch_news(NOW, get=feeds(**{"splash247.com": "banned_news_feed.xml"}))
    banned = [d for d in result["dropped"] if d["source_id"] == "splash247"]
    assert len(banned) == 2
    assert all(d["reason"] == "names a banned source" and d["link"] is None for d in banned)
    assert not any("splash247.com/test-" in i["link"] for i in all_items(result))


@pytest.mark.parametrize("excerpt, author", [
    ("By Jan Wolfe Oct 11 (Reuters) – Text follows.", "Jan Wolfe"),
    ("By Catherine Lucey and María Paula Mijares Torres Oct 11, 2026 (Bloomberg) – Text.",
     "Catherine Lucey and María Paula Mijares Torres"),
    ("By Jane Example Owners say things without a break.", None),
])
def test_byline_needs_a_clear_break(excerpt, author):
    from modules.morning_brief.news import BYLINE
    match = BYLINE.match(excerpt)
    assert (match.group(1) if match else None) == author


def test_digit_free_excerpt_needs_some_text():
    assert digit_free_excerpt("Rates rose 5%. Short.") is None


# ── Duplicates ───────────────────────────────────────────────────────────────

def test_same_story_in_two_feeds_is_kept_once_with_both_credited():
    result = fetch_news(NOW, get=feeds(**{"gcaptain.com": "news/special_cases.xml",
                                          "maritime-executive.com": "news/duplicate_story.xml"}))
    matches = [i for i in all_items(result) if "port strike talks" in i["headline"].lower()]
    assert len(matches) == 1
    assert matches[0]["publisher"] == "gCaptain"            # earliest report kept
    assert matches[0]["also_reported_by"] == ["The Maritime Executive"]


# ── Feed failures ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture, expected", [
    (("news/malformed.xml",), "not valid XML"),
    (("news/error_page.html",), "unrecognised feed format"),
    (("news/empty_feed.xml",), "no items"),
    (("news/error_page.html", 403), "403"),
])
def test_failed_feed_is_recorded_and_others_continue(fixture, expected):
    result = fetch_news(NOW, get=feeds(**{"splash247.com": fixture}))
    assert expected in result["feed_errors"]["splash247"]
    assert {i["publisher"] for i in all_items(result)} == {"gCaptain", "The Maritime Executive"}


def test_every_feed_failing_gives_empty_sections():
    bad = ("news/malformed.xml",)
    result = fetch_news(NOW, get=feeds(**{h: bad for h in RECORDED}))
    assert set(result["feed_errors"]) == set(FEEDS)
    assert all(items == [] for items in result["sections"].values())
