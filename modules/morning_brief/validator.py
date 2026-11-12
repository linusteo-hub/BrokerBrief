"""
modules/morning_brief/validator.py

The publishing gate. Nothing reaches the public brief without passing it.

Two levels:

1. Item checks on what the language model wrote (check_summary, check_why).
   The writer retries a failing item once, then withholds it: the item is
   published as headline and link only. A bad summary costs one summary,
   not the brief.

2. Whole-brief checks on the final Markdown (validate_brief), and a re-check
   of the payload (validate_payload). These look for faults that only a bug
   in BrokerBrief's own code could cause, so a failure here is "fail closed":
   nothing is published that day and the run reports the problems.

Every check returns a list of Problem; an empty list means it passed.

Why the number check normalises: the same figure can be written "1,234.5"
or "1234.50". Both are turned into the number 1234.5 before comparing, so
formatting never causes a false alarm, and a genuinely different number never
slips through.
"""

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from modules.morning_brief.allowlist import ALLOWLIST, mentions_banned_source


@dataclass(frozen=True)
class Problem:
    code: str          # short machine-readable reason, e.g. "number_not_in_payload"
    message: str       # plain English
    where: str = ""    # the line, item id or figure id concerned

    def to_dict(self) -> dict:
        return asdict(self)


# ── Numbers ──────────────────────────────────────────────────────────────────

# A number with comma thousands separators (1,234.5), or a plain one (1234.50).
# A comma counts as a thousands separator only when exactly three digits follow,
# so "5,3" is read as two numbers, not as 53.
NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")


def to_number(token: str) -> Optional[Decimal]:
    try:
        return Decimal(token.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def numbers_in(text: str) -> list:
    """[(token as written, Decimal)] for every number in `text`."""
    found = []
    for match in NUMBER.finditer(text):
        value = to_number(match.group(0))
        if value is not None:
            found.append((match.group(0), value))
    return found


# Payload string fields whose numbers may legitimately appear in the brief.
TEXT_KEYS = {"display", "abs_display", "pct_display", "previous_display", "as_of_display",
             "brief_date_display", "published_display", "label", "headline", "reason", "title",
             "basis", "compared_with", "credit", "name", "cadence", "generated_at", "trial_notice",
             "publisher", "author", "licence"}


def _walk_strings(node, key=None):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v, key)
    elif isinstance(node, str) and key in TEXT_KEYS:
        yield node


def allowed_numbers(payload: dict) -> set:
    """Every number the brief may contain: those in the payload's display text,
    plus section numbers and source-tag numbers, which the template adds."""
    allowed = {Decimal(n).normalize() for n in range(1, 10)}           # "## 1. Prices" … "## 9."
    allowed |= {to_number(s["tag"][1:]) for s in payload.get("sources", [])}
    for text in _walk_strings(payload):
        allowed |= {value for _, value in numbers_in(strip_urls(text)[0])}
    return allowed


# ── Links ────────────────────────────────────────────────────────────────────

MD_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")
BARE_URL = re.compile(r"https?://[^\s)\]>]+")


def strip_urls(text: str) -> tuple:
    """(text with every URL removed, [urls]). Numbers inside URLs (article ids,
    query strings) are not figures and must not be number-checked."""
    urls = MD_LINK.findall(text)
    text = MD_LINK.sub("]()", text)
    urls += BARE_URL.findall(text)
    return BARE_URL.sub("", text), [u.rstrip(".,;") for u in urls]


def allowed_urls(payload: dict) -> set:
    urls = set()
    for source in payload.get("sources", []):
        urls |= {source.get("url"), source.get("terms_url")}
        urls |= set(strip_urls(source.get("credit", ""))[1])
    for item in iter_payload_items(payload):
        if item.get("link"):
            urls.add(item["link"])
    return {u for u in urls if u}


def iter_payload_items(payload: dict):
    for section in payload.get("sections", {}).values():
        for sub in section.get("subsections", {"_": section}).values():
            yield from sub.get("items", [])


def figures(payload: dict) -> list:
    return [item for item in iter_payload_items(payload) if "display" in item]


def news_items(payload: dict) -> list:
    return [item for item in iter_payload_items(payload) if "headline" in item]


# ── Directions ───────────────────────────────────────────────────────────────

UP_WORDS = ("rose", "rise", "rises", "risen", "rising", "up", "increased", "increase", "increases",
            "higher", "gained", "gain", "climbed", "climb", "firmed")
DOWN_WORDS = ("fell", "fall", "falls", "fallen", "falling", "down", "decreased", "decrease", "decreases",
              "lower", "dropped", "drop", "declined", "decline", "eased", "slipped")
FLAT_WORDS = ("unchanged", "flat", "steady", "stable")
DIRECTION_OF = {**{w: "up" for w in UP_WORDS}, **{w: "down" for w in DOWN_WORDS},
                **{w: "flat" for w in FLAT_WORDS}}
DIRECTION_WORD = re.compile(r"\b(" + "|".join(sorted(DIRECTION_OF, key=len, reverse=True)) + r")\b", re.I)

# Short names a writer might use for a figure, beyond its full label.
SHORT_NAMES = {"brent_spot": ("Brent",), "ulsd_nyh": ("diesel", "ULSD")}
AMOUNT_WINDOW = 40      # characters after a direction word in which its amount must start


def figure_names(figure: dict) -> tuple:
    label = re.split(r"[(,]", figure.get("label", ""))[0].strip()
    return tuple(n for n in (label, *SHORT_NAMES.get(figure.get("id"), ())) if n)


def _norm(text: str) -> str:
    return " ".join(text.replace("\\", "").split()).lower()


def check_directions(text: str, payload: dict) -> list:
    """Every direction word must agree with the payload's `direction`.

    - A direction word followed (within a few words) by a change amount is
      checked against the change(s) with that amount. If no change with that
      amount has that direction, it fails ("rose USD 0.07/bbl" when it fell).
    - A direction word with no amount, in a sentence that names exactly one
      figure, is checked against that figure's first change ("Brent rose").
    """
    problems = []
    figs = figures(payload)
    by_amount: dict = {}
    for fig in figs:
        for change in fig.get("changes", []):
            by_amount.setdefault(_norm(change["abs_display"]), []).append((fig, change))

    for sentence in re.split(r"(?<=[.;!?])\s+|\n", strip_urls(text)[0]):
        lowered = _norm(sentence)
        named = [fig for fig in figs if any(_norm(n) in lowered for n in figure_names(fig))]
        for match in DIRECTION_WORD.finditer(lowered):
            word = match.group(1).lower()
            claimed = DIRECTION_OF[word]
            after = lowered[match.end():match.end() + AMOUNT_WINDOW]
            amount_hits = [(fig, change) for amount, pairs in by_amount.items()
                           if re.match(rf"\s*(by\s+|of\s+|to\s+)?{re.escape(amount)}", after) for fig, change in pairs]
            if named:
                scoped = [(f, c) for f, c in amount_hits if f in named]
                amount_hits = scoped or amount_hits
            if amount_hits:
                if not any(change["direction"] == claimed for _, change in amount_hits):
                    actual = sorted({change["direction"] for _, change in amount_hits})
                    problems.append(Problem("direction_mismatch",
                                            f'"{word}" but the payload direction is {" / ".join(actual)}',
                                            sentence.strip()))
            elif len(named) == 1 and named[0].get("changes"):
                actual = named[0]["changes"][0]["direction"]
                if actual != claimed:
                    problems.append(Problem("direction_mismatch",
                                            f'"{word}" but {named[0]["id"]} moved {actual}', sentence.strip()))
    return problems


# ── Item checks (model output) ───────────────────────────────────────────────

NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|"
    r"thousands?|millions?|billions?|trillions?|dozens?|percent|per cent|half|double|triple|quarter|twice|"
    r"\w+fold|\w+-fold)\b|%",
    re.I)


def has_numeric_character(text: str) -> bool:
    """Any digit in any script, or a numeric symbol such as ½, ² or Roman Ⅻ."""
    import unicodedata
    return any(unicodedata.category(ch) in ("Nd", "No", "Nl") for ch in text)
MARKUP = re.compile(r"[\[\]<>`#*_|@]|https?://|www\.|\b[a-z0-9-]+\.(com|org|net|io|co|gov|sg|uk)\b", re.I)
HEDGES = re.compile(r"\b(suggests?|may|might|could|would|likely|appears?|indicates?|points? to|if)\b", re.I)
SUMMARY_MAX_WORDS = 55
SUMMARY_MAX_SENTENCES = 2
WHY_MAX_WORDS = 40
QUOTE_MAX_WORDS = 10    # longest run of words copied from the headline or excerpt


def _words(text: str) -> list:
    return re.findall(r"[\w']+", text.lower().replace("’", "'"))


def longest_copied_run(text: str, source: str) -> int:
    """Length of the longest run of consecutive words `text` shares with `source`."""
    a, b = _words(text), _words(source)
    best = 0
    previous = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def _common_checks(text: str, where: str) -> list:
    problems = []
    if re.search(r"\d", text) or has_numeric_character(text):
        problems.append(Problem("digit", "contains a digit or numeric symbol", where))
    words = NUMBER_WORDS.findall(text)
    if words:
        problems.append(Problem("number_word", f"contains a number in words ({', '.join(sorted(set(w.lower() for w in words)))})", where))
    banned = mentions_banned_source(text)
    if banned:
        problems.append(Problem("banned_source", f"names a banned source ({banned})", where))
    if MARKUP.search(text) or "\n" in text:
        problems.append(Problem("markup", "contains a link, markup or a line break", where))
    if re.search(r"\b(recommend|we advise|you should|investors should|ought to)\b", text, re.I):
        problems.append(Problem("advice", "reads as advice", where))
    return problems


def check_summary(summary: str, item: dict) -> list:
    """Problems with a model-written news summary for `item`."""
    where = item.get("id", "")
    text = (summary or "").strip()
    if not text:
        return [Problem("empty", "no summary", where)]
    problems = _common_checks(text, where)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) > SUMMARY_MAX_SENTENCES:
        problems.append(Problem("too_many_sentences", f"{len(sentences)} sentences (limit {SUMMARY_MAX_SENTENCES})", where))
    if len(_words(text)) > SUMMARY_MAX_WORDS:
        problems.append(Problem("too_long", f"{len(_words(text))} words (limit {SUMMARY_MAX_WORDS})", where))
    copied = max(longest_copied_run(text, item.get("excerpt") or ""), longest_copied_run(text, item.get("headline", "")))
    if copied > QUOTE_MAX_WORDS:
        problems.append(Problem("copied_run", f"copies {copied} consecutive words from the feed (limit {QUOTE_MAX_WORDS})", where))
    return problems


def check_why(why: str, item: dict) -> list:
    """Problems with a model-written 'why it matters' note. It is interpretation,
    so it must be phrased as interpretation ("this suggests…", "could…")."""
    where = item.get("id", "")
    text = (why or "").strip()
    if not text:
        return [Problem("empty", "no 'why it matters' note", where)]
    problems = _common_checks(text, where)
    if not HEDGES.search(text):
        problems.append(Problem("not_hedged", "states interpretation as fact (no 'suggests', 'may', 'could'…)", where))
    if len(_words(text)) > WHY_MAX_WORDS:
        problems.append(Problem("too_long", f"{len(_words(text))} words (limit {WHY_MAX_WORDS})", where))
    copied = max(longest_copied_run(text, item.get("excerpt") or ""), longest_copied_run(text, item.get("headline", "")))
    if copied > QUOTE_MAX_WORDS:
        problems.append(Problem("copied_run", f"copies {copied} consecutive words from the feed", where))
    return problems


# ── Payload re-check ─────────────────────────────────────────────────────────

def validate_payload(payload: dict) -> list:
    """Re-check every figure's range and staleness at publishing time, against
    the brief date. The fetchers already did this; repeating it here means a
    payload that was built, stored and published later (or a fetcher bug)
    still cannot publish a stale or implausible figure."""
    problems = []
    brief_date = date.fromisoformat(payload["brief_date"])
    tags = {s["tag"] for s in payload.get("sources", [])}
    for key, section in payload.get("sections", {}).items():
        for sub_key, sub in section.get("subsections", {"": section}).items():
            name = f"{key}.{sub_key}" if sub_key else key
            if sub.get("status") == "ok" and not sub.get("items") and "subsections" not in sub:
                problems.append(Problem("ok_but_empty", "section marked ok with no items", name))
            if sub.get("status") in ("missing", "not_covered") and not sub.get("reason"):
                problems.append(Problem("no_reason", "empty section without a reason", name))
    for fig in figures(payload):
        where = fig.get("id", "")
        source = ALLOWLIST.get(fig.get("source_id"))
        if source is None or not source.redistributable:
            problems.append(Problem("source_not_allowed", f"figure from {fig.get('source_id')!r}", where))
            continue
        if fig.get("source_tag") not in tags:
            problems.append(Problem("unknown_source_tag", f"figure has tag {fig.get('source_tag')!r}", where))
        low_high = fig.get("plausible_range")
        if not low_high:
            problems.append(Problem("no_range", "figure carries no plausible range", where))
        elif not (low_high[0] <= fig["value"] <= low_high[1]):
            problems.append(Problem("out_of_range", f"{fig['display']} is outside {low_high[0]:g}–{low_high[1]:g}", where))
        as_of = date.fromisoformat(fig["as_of"])
        if source.max_age is not None and brief_date - as_of > source.max_age:
            problems.append(Problem("stale", f"dated {fig['as_of_display']}, more than {source.max_age.days} days "
                                             f"before the brief date", where))
        if as_of > brief_date:
            problems.append(Problem("future_date", f"dated {fig['as_of_display']}, after the brief date", where))
        for change in fig.get("changes", []):
            if change.get("direction") not in ("up", "down", "flat"):
                problems.append(Problem("no_direction", "a change has no valid direction", where))
    return problems


TAG = re.compile(r"\[S(\d+)\]")


# ── Free-text check ──────────────────────────────────────────────────────────

def check_numbers(text: str, payload: dict) -> list:
    """Every number in `text` must appear in the payload (after normalising
    thousands separators, trailing zeros and currency symbols)."""
    allowed = allowed_numbers(payload)
    problems = []
    for line in strip_urls(text)[0].splitlines():
        for token, value in numbers_in(TAG.sub("", line)):
            if value not in allowed:
                problems.append(Problem("number_not_in_payload", f"{token} is not in the payload", line.strip()))
    return problems


def check_text(text: str, payload: dict) -> list:
    """Numbers and directions in any prose about the payload's figures."""
    return check_numbers(text, payload) + check_directions(text, payload)


# ── Whole-brief gate ─────────────────────────────────────────────────────────

NEWS_HEADINGS = ("## 4. Sale & Purchase", "## 5. Events and why they matter", "### Freight rate direction")
BOLD = re.compile(r"\*\*((?:\\.|[^*\\])+?)\*\*")
WHY_LABEL = "Why it matters (our interpretation):"


def unescape(text: str) -> str:
    return re.sub(r"\\([\\`*_\[\]<>#|])", r"\1", text)


def _news_lines(markdown: str) -> list:
    """News item lines (list items and their indented 'why it matters' notes)
    inside the news blocks: S&P, Events and freight rate direction. The
    template's own notes in those blocks (cadence, empty-section reasons) are
    not news text and are covered by the number check instead."""
    lines, inside = [], False
    for line in markdown.splitlines():
        if line.startswith("#"):
            inside = line.startswith(NEWS_HEADINGS)
            continue
        if inside and (line.startswith("- ") or line.startswith("  ")):
            lines.append(line)
    return lines


def validate_brief(markdown: str, payload: dict) -> list:
    """Code-level checks on the final brief. Any problem means: do not publish."""
    problems = []
    text, urls = strip_urls(markdown)

    # Structure: title with the brief date, and no silent gaps.
    if not markdown.startswith(f"# BrokerBrief Morning Brief: {payload['brief_date_display']}\n"):
        problems.append(Problem("structure", "title line missing or has the wrong date"))
    for heading in ("## 1. Prices", "## 2. Singapore bunker sales", "## 3. Freight", "## 4. Sale & Purchase",
                    "## 5. Events and why they matter", "## Sources"):
        if f"\n{heading}\n" not in markdown:
            problems.append(Problem("structure", f"section heading missing: {heading}"))
    # No silent gaps: every section and subsection must show at least one item
    # or say why it is empty. Freight's own body only introduces its subsections.
    for block in re.split(r"\n(?=#{2,3} )", markdown)[1:]:
        heading, _, body = block.partition("\n")
        if heading in ("## Sources", "## 3. Freight"):
            continue
        shown = [l for l in body.splitlines()
                 if l.startswith("- ") or l.startswith(("No verified data today:", "Not covered:"))]
        if not shown:
            problems.append(Problem("silent_gap", "section has neither content nor a reason it is empty", heading))
    if "\n## 3. Freight\n" in markdown and "\n### " not in markdown.split("\n## 3. Freight\n", 1)[1].split("\n## ", 1)[0]:
        problems.append(Problem("silent_gap", "Freight shows none of its subsections", "## 3. Freight"))

    # Links: only payload links and source pages.
    allowed = allowed_urls(payload)
    for url in urls:
        if url not in allowed:
            problems.append(Problem("unknown_link", "link not in the payload", url))

    # Numbers: every number must come from the payload.
    problems += check_numbers(markdown, payload)

    # Source tags: each must exist; every figure line must carry one.
    tags = {s["tag"] for s in payload.get("sources", [])}
    for tag in set(TAG.findall(markdown)):
        if f"S{tag}" not in tags:
            problems.append(Problem("unknown_source_tag", f"[S{tag}] is not in the sources list"))
    # Each figure must appear on one line together with its own label and tag,
    # so a value cannot be shown next to another figure's name.
    for fig in figures(payload):
        own = [l for l in markdown.splitlines()
               if f"**{fig['label']}:** {fig['display']}," in unescape(l)]
        if not own:
            problems.append(Problem("figure_missing", "figure not shown next to its own label", fig["id"]))
        elif not any(f"[{fig['source_tag']}]" in l for l in own):
            problems.append(Problem("untagged_figure", f"no [{fig['source_tag']}] next to the figure", fig["id"]))

    # Banned names anywhere.
    banned = mentions_banned_source(markdown)
    if banned:
        problems.append(Problem("banned_source", f"names a banned source ({banned})"))

    # Directions: BrokerBrief's own figure statements only. News lines are the
    # publishers' words (a headline may say "rates climb"), not claims about
    # our figures, so they are excluded here and covered by the news checks.
    news = set(_news_lines(markdown))
    problems += check_directions("\n".join(l for l in markdown.splitlines() if l not in news), payload)

    # News lines: headlines verbatim from the payload; no digits outside them.
    headlines = {item["headline"] for item in news_items(payload)}
    # Text the template copies from the payload into a news line: dates and
    # publisher names ("Splash247" contains digits).
    copied = {item.get("published_display", "") for item in news_items(payload)}
    copied |= {name for item in news_items(payload)
               for name in [item.get("publisher", ""), item.get("author") or ""] + item.get("also_reported_by", [])}
    copied = sorted((c for c in copied if c), key=len, reverse=True)
    for line in _news_lines(markdown):
        rest = strip_urls(line)[0]
        for bold in BOLD.findall(line):
            plain = unescape(bold)
            if plain in headlines:
                rest = rest.replace(f"**{bold}**", "")
            elif plain != WHY_LABEL:
                problems.append(Problem("headline_not_in_payload", "bold text is not a payload headline", plain))
        rest = TAG.sub("", rest)
        for c in copied:
            rest = rest.replace(c, "")
        if re.search(r"\d", rest):
            problems.append(Problem("digit_in_news_text", "a digit outside the headline, date and tag", line.strip()))
        words = NUMBER_WORDS.findall(unescape(rest))
        if words:
            problems.append(Problem("number_word_in_news_text", f"number in words ({', '.join(words)})", line.strip()))
    return problems


def problems_to_dicts(problems: Iterable[Problem]) -> list:
    return [p.to_dict() for p in problems]
