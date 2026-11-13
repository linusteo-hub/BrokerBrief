"""
modules/morning_brief/writer.py

Turns a checked payload into the published Markdown brief.

Division of labour ("code writes the facts, the model writes summaries"):

- Code (render_brief) writes everything factual: headings, every figure with
  its date, change and direction word, empty-section notices, credits and the
  sources list. All of it is copied from payload display strings.
- The language model writes only two kinds of prose, and never sees a figure:
  a summary of each news item (from its headline and digit-free excerpt) and,
  for Events, one hedged "why it matters" sentence.

Every model sentence is checked (validator.check_summary / check_why). A
failing item is sent back once with the problems listed; if it fails again it
is withheld and published as headline and link only. Then the whole brief
goes through validator.validate_brief, and any problem there stops
publication (BriefRefused): those can only come from a bug in our own code.

If the model cannot be reached at all (no key, expired key, no credit, outage,
refusal), the brief still goes out with every news item as headline and link,
and the report says why. That is the fail-safe path for unattended runs.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from modules.morning_brief.validator import (
    Problem, check_summary, check_why, news_items, problems_to_dicts, validate_brief, validate_payload,
)

MODEL = "claude-haiku-5-5"
EFFORT = "low"           # short, constrained writing; see docs for the model comparison
MAX_TOKENS = 8000
MAX_ATTEMPTS = 2         # first try + one retry for the items that failed

# USD per million tokens, from Anthropic's pricing page (read 12-11-2026).
# Used only to report the cost of each run; billing is Anthropic's.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}

SYSTEM_PROMPT = """You write short news summaries for the BrokerBrief Morning Brief, read by students and early-career people interested in shipping markets.

You receive a JSON list of news items. Each has an id, the section it belongs to, the headline, an excerpt from the publisher's feed, the publisher and sometimes the author. You return one entry per id.

For every item, write "summary": what happened, in your own words, in one or two plain sentences of at most fifty words.
For items whose "needs_why" is true, also write "why_it_matters": one sentence of interpretation for a shipping reader, phrased as interpretation ("This suggests…", "This could…", "may"), never as fact. For other items, return an empty string.

Rules, which are checked by code; an item that breaks one is not published:
1. No numbers of any kind: no digits, and no numbers written as words (no "two", "dozen", "million", "percent", "half"). Write "several", "a large", "rose", "fell" instead. Feed excerpts often quote licensed index figures, so leave every figure out.
2. Use only what the headline and excerpt say. Do not add facts, names, causes or background you know from elsewhere.
3. Your own words: never copy more than ten consecutive words from the headline or excerpt.
4. Plain text only: no links, no Markdown, no quotation marks around copied text, no line breaks.
5. Do not name any index, price assessment or market-data provider. Do not give trading or investment advice.
6. Define a technical term in brackets the first time you use it, e.g. "VLCC (very large crude carrier)".
7. British spelling."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["id", "summary", "why_it_matters"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


# Errors that mean our own code is wrong, not that the API is unavailable.
PROGRAMMING_ERRORS = (TypeError, AttributeError, NameError, ImportError)


class BriefRefused(Exception):
    """The final brief failed a code-level check; nothing may be published."""

    def __init__(self, problems: list):
        self.problems = problems
        super().__init__(f"{len(problems)} code-level problem(s): "
                         + "; ".join(f"{p.code}: {p.message}" for p in problems[:5]))


@dataclass
class WriterReport:
    status: str = "ok"                      # ok | partial | no_model | model_unavailable
    model: Optional[str] = None
    detail: str = ""
    attempts: list = field(default_factory=list)     # per call: items sent, tokens, cost
    withheld: dict = field(default_factory=dict)     # item id -> [problem dicts]
    written: list = field(default_factory=list)      # item ids with an accepted summary

    def to_dict(self) -> dict:
        total_cost = sum(a.get("cost_usd") or 0 for a in self.attempts)
        return {"status": self.status, "model": self.model, "detail": self.detail,
                "attempts": self.attempts, "written": self.written, "withheld": self.withheld,
                "total_cost_usd": round(total_cost, 6)}


# ── What the model is asked to write ─────────────────────────────────────────

def items_for_model(payload: dict) -> list:
    """The items the model may summarise. Wire items and items without a
    usable excerpt (summary_allowed False) are never sent: they are published
    as headline and link only, whatever the model would say."""
    out = []
    for item in news_items(payload):
        if not item.get("summary_allowed"):
            continue
        out.append({"id": item["id"], "section": item["section"], "headline": item["headline"],
                    "excerpt": item.get("excerpt") or "", "publisher": item["publisher"],
                    "author": item.get("author"), "needs_why": item["section"] == "events"})
    return out


def _classify_error(error: Exception) -> str:
    """A short, stable reason for an API failure, for the run report and the alert."""
    status = getattr(error, "status_code", None)
    message = str(getattr(error, "message", "") or error).lower()
    if status == 401:
        return "authentication failed (API key missing, wrong or revoked)"
    if status == 403:
        return "permission denied for this API key"
    if status == 400 and ("credit" in message or "billing" in message):
        return "out of credit or spend limit reached"
    if status == 429:
        return "rate limited"
    if status is not None and status >= 500:
        return f"Anthropic API error (HTTP {status})"
    if status is not None:
        return f"request rejected (HTTP {status})"
    return f"could not reach the API ({type(error).__name__})"


def _cost(model: str, usage) -> Optional[float]:
    prices = PRICES.get(model)
    if prices is None or usage is None:
        return None
    input_tokens = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) \
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return (input_tokens * prices[0] + (getattr(usage, "output_tokens", 0) or 0) * prices[1]) / 1_000_000


def call_model(client, items: list, model: str, feedback: Optional[dict] = None) -> tuple:
    """One request. Returns (dict id -> {"summary", "why_it_matters"}, attempt record).
    Raises on an API error; returns ({}, record) on a refusal or unreadable output."""
    request_items = []
    for item in items:
        entry = dict(item)
        if feedback and item["id"] in feedback:
            entry["previous_attempt_failed_because"] = feedback[item["id"]]
        request_items.append(entry)
    user = ("Write the summaries for these items. Return JSON only.\n\n"
            + json.dumps(request_items, ensure_ascii=False, indent=1))
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    usage = getattr(response, "usage", None)
    record = {"items_sent": len(items), "stop_reason": getattr(response, "stop_reason", None),
              "input_tokens": getattr(usage, "input_tokens", None),
              "output_tokens": getattr(usage, "output_tokens", None),
              "cost_usd": _cost(model, usage)}
    if record["stop_reason"] == "refusal":
        return {}, record
    try:
        text = next(block.text for block in response.content if getattr(block, "type", None) == "text")
        data = json.loads(text)
        written = {entry["id"]: {"summary": str(entry.get("summary", "")),
                                 "why_it_matters": str(entry.get("why_it_matters", ""))}
                   for entry in data["items"]}
    except (StopIteration, KeyError, TypeError, ValueError) as error:
        record["parse_error"] = type(error).__name__
        return {}, record
    return written, record


def check_written(item: dict, written: Optional[dict]) -> list:
    if written is None:
        return [Problem("missing", "the model returned nothing for this item", item["id"])]
    problems = check_summary(written["summary"], item)
    if item["needs_why"]:
        problems += check_why(written["why_it_matters"], item)
    return problems


def write_summaries(payload: dict, client=None, model: str = MODEL) -> tuple:
    """Returns ({item id: {"summary", "why_it_matters"}} for accepted items, WriterReport)."""
    report = WriterReport(model=model if client else None)
    items = items_for_model(payload)
    if not items:
        report.status, report.detail = "ok", "no news item needed a summary"
        return {}, report
    if client is None:
        report.status = "no_model"
        report.detail = "no language model in use: news is published as headline and link only"
        report.withheld = {i["id"]: [Problem("no_model", report.detail).to_dict()] for i in items}
        return {}, report

    accepted: dict = {}
    pending, feedback = items, None
    last_problems: dict = {}
    trouble = []          # what went wrong with the model itself, per attempt
    for attempt in range(MAX_ATTEMPTS):
        try:
            written, record = call_model(client, pending, model, feedback)
        except PROGRAMMING_ERRORS:
            raise         # a bug in our code must surface, not pass as "API unavailable"
        except Exception as error:      # the SDK's API errors, timeouts, connection failures
            record = {"items_sent": len(pending), "error": _classify_error(error)}
            report.attempts.append(record)
            trouble.append(record["error"])
            break
        report.attempts.append(record)
        if record.get("stop_reason") == "refusal":
            trouble.append("the model declined the request")
        elif record.get("parse_error"):
            trouble.append(f"the model's output could not be read ({record['parse_error']})")
        failed, feedback = [], {}
        for item in pending:
            problems = check_written(item, written.get(item["id"]))
            if problems:
                failed.append(item)
                last_problems[item["id"]] = problems
                feedback[item["id"]] = "; ".join(p.message for p in problems)
            else:
                accepted[item["id"]] = written[item["id"]]
                last_problems.pop(item["id"], None)
        pending = failed
        if not pending:
            break

    # Status is decided once, from the outcome: nothing written because of the
    # model itself is "model_unavailable"; some withheld is "partial".
    report.detail = "; ".join(dict.fromkeys(trouble))
    for item in items:
        if item["id"] not in accepted:
            problems = last_problems.get(item["id"]) or [Problem("not_written", report.detail or "not written", item["id"])]
            report.withheld[item["id"]] = problems_to_dicts(problems)
    report.written = sorted(accepted)
    if not accepted and trouble:
        report.status = "model_unavailable"
    elif report.withheld:
        report.status = "partial"
    else:
        report.status = "ok"
    return accepted, report


# ── Rendering (code only) ────────────────────────────────────────────────────

ESCAPE = re.compile(r"([\\`*_\[\]<>#|])")
DIRECTION_WORDS = {"up": "Up", "down": "Down", "flat": "Unchanged"}


def esc(text: str) -> str:
    """Escape Markdown so feed text cannot add links, emphasis or headings."""
    return ESCAPE.sub(r"\\\1", text or "")


def render_figure(fig: dict, previous: Optional[dict]) -> str:
    when = f"for {fig['as_of_display']}" if fig.get("period") == "month" else f"as of {fig['as_of_display']}"
    line = f"- **{esc(fig['label'])}:** {fig['display']}, {when} [{fig['source_tag']}]."
    for change in fig.get("changes", []):
        word = DIRECTION_WORDS[change["direction"]]
        if change["direction"] == "flat":
            line += f" {word} from {change['compared_with']} ({change['basis']})."
        else:
            pct = f" ({change['pct_display']})" if change.get("pct_display") else ""
            line += f" {word} {change['abs_display']}{pct} from {change['compared_with']} ({change['basis']})."
    if previous and previous.get("as_of") == fig["as_of"] and previous.get("value") == fig["value"]:
        line += " Same figure as in the previous brief: the source has not published a newer one."
    return line


def render_news(item: dict, accepted: dict) -> list:
    who = item["publisher"] + (f", by {item['author']}" if item.get("author") else "")
    line = f"- **{esc(item['headline'])}** ({esc(who)}, {item['published_display']})."
    written = accepted.get(item["id"])
    if item.get("wire_agency"):
        line += f" {esc(item['wire_agency'])} wire story: headline and link only."
    elif written:
        line += f" {esc(written['summary'])}"
    if item.get("also_reported_by"):
        line += f" Also reported by {esc(', '.join(item['also_reported_by']))}."
    line += f" [Read the story]({item['link']}) [{item['source_tag']}]"
    lines = [line]
    if written and item["section"] == "events" and written.get("why_it_matters"):
        lines.append(f"  **Why it matters (our interpretation):** {esc(written['why_it_matters'])}")
    return lines


def plain_reason(reason: Optional[str]) -> str:
    """A section's empty-reason, safe to publish: a feed's error message can
    quote the request URL (with a redacted key, or a query string), so URLs
    are removed. (Keeping the host was tried: a host such as "cdn123.net"
    then failed the number check and stopped the brief.)"""
    text = re.sub(r"https?://\S+", "(address removed)", reason or "no reason recorded")
    return esc(text)


def render_empty(section: dict) -> list:
    if section["status"] == "not_covered":
        return [f"Not covered: {plain_reason(section['reason'])}"]
    return [f"No verified data today: {plain_reason(section['reason'])}"]


def render_items(section: dict, accepted: dict, previous_figs: dict) -> list:
    if section["status"] != "ok":
        return render_empty(section)
    lines = []
    for item in section["items"]:
        if "display" in item:
            lines.append(render_figure(item, previous_figs.get(item["id"])))
        else:
            lines += render_news(item, accepted)
    return lines


CADENCE_NOTES = {
    "prices": "Latest available values. The source publishes daily prices once a week, so each figure shows its own date.",
    "bunker_sales": "Monthly totals from the Maritime and Port Authority of Singapore, published about three weeks after "
                    "the month ends; the latest month is a preliminary estimate. Volumes, not prices.",
    "freight": "Weekly section.",
    "sale_and_purchase": "Weekly section: deals reported in the past week, up to the brief date.",
    "events": "Stories published since the previous brief.",
}


def render_brief(payload: dict, accepted: dict, previous_payload: Optional[dict] = None) -> str:
    previous_figs = {}
    if previous_payload:
        from modules.morning_brief.validator import figures as _figures
        previous_figs = {f["id"]: f for f in _figures(previous_payload)}
    s = payload["sections"]
    out = [f"# BrokerBrief Morning Brief: {payload['brief_date_display']}", "",
           f"> **{payload['trial_notice']}.** A student portfolio project. " + (
               "Figures are copied from public sources by code; news summaries are written by a language model "
               "from feed headlines and excerpts and checked by code before publishing."
               if accepted else
               "Everything here is written by code from public sources; no language model is used.")
           + " Not investment or trading advice.", ""]

    def section(heading: str, key: str):
        out.extend([heading, "", f"*{CADENCE_NOTES[key]}*", ""])
        out.extend(render_items(s[key], accepted, previous_figs))
        out.append("")

    section("## 1. Prices", "prices")
    section("## 2. Singapore bunker sales", "bunker_sales")

    freight = s["freight"]
    out.extend(["## 3. Freight", "", f"*{CADENCE_NOTES['freight']}*", ""])
    if freight["status"] != "ok" and not any(sub["status"] == "ok" for sub in freight["subsections"].values()):
        out.extend(render_empty(freight) + [""])
    for sub in freight["subsections"].values():
        out.extend([f"### {esc(sub['title'])}", ""])
        out.extend(render_items(sub, accepted, previous_figs))
        out.append("")

    section("## 4. Sale & Purchase", "sale_and_purchase")
    section("## 5. Events", "events")

    out.extend(["## Sources", ""])
    for source in payload["sources"]:
        retrieved = (f" Retrieved for this brief on {payload['brief_date_display']}."
                     if source.get("kind") == "data" else "")
        out.append(f"- [{source['tag']}] **{esc(source['name'])}** ({esc(source['publisher'])}). "
                   f"{esc(source['credit'])}.{retrieved} Terms: {source['terms_url']}")
    out.extend(["", f"*Generated automatically for {payload['brief_date_display']}. "
                    "Each figure shows the date the source reports for it.*", ""])
    return "\n".join(out)


# ── Whole pipeline ───────────────────────────────────────────────────────────

def build_brief(payload: dict, client=None, model: str = MODEL,
                previous_payload: Optional[dict] = None) -> tuple:
    """Returns (markdown, report dict). Raises BriefRefused if the payload or
    the rendered brief fails a code-level check; nothing may then be published."""
    payload_problems = validate_payload(payload)
    if payload_problems:
        raise BriefRefused(payload_problems)
    accepted, writer = write_summaries(payload, client, model)
    markdown = render_brief(payload, accepted, previous_payload)
    brief_problems = validate_brief(markdown, payload)
    if brief_problems:
        raise BriefRefused(brief_problems)
    return markdown, {"brief_date": payload["brief_date"], "published": True,
                      "writer": writer.to_dict(), "payload_checks": [], "brief_checks": [],
                      "section_status": section_status(payload)}


def public_payload(payload: dict) -> dict:
    """The payload as it may be archived publicly. News excerpts are the
    publishers' own text (digit-free, but still theirs), used only to brief the
    model; the public archive keeps headline, link and credit, as the brief does."""
    import copy
    public = copy.deepcopy(payload)
    from modules.morning_brief.validator import news_items as _news
    for item in _news(public):
        item.pop("excerpt", None)
    return public


def section_status(payload: dict) -> dict:
    """{section key: status}, with Freight's subsections as freight.<key>. The
    alerting step reads this to spot sections that stay empty day after day."""
    out = {}
    for key, section in payload["sections"].items():
        out[key] = section["status"]
        for sub_key, sub in section.get("subsections", {}).items():
            out[f"{key}.{sub_key}"] = sub["status"]
    return out


def make_client(api_key: Optional[str]):
    """The real Anthropic client, or None when no key is configured."""
    if not api_key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120.0)
