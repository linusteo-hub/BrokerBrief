"""
tests/test_morning_brief_writer.py

The writer and the publishing gate, with a fake model (tests/fake_model.py):
no network, no API key. Covers the Phase 2 design: code writes the facts,
the model writes summaries; a failing summary is retried once, then withheld;
a code-level violation stops publication (fail closed); a model that cannot
be reached still leaves a published brief, with news as headline and link.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from modules.morning_brief import writer
from modules.morning_brief.validate import run_cases
from modules.morning_brief.validator import check_numbers, news_items, validate_brief
from modules.morning_brief.writer import BriefRefused, build_brief, items_for_model, render_brief
from tests.fake_model import FakeAPIError, FakeClient
from tests.fixture_http import FIXTURES

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = json.loads((FIXTURES / "payload/from_fixtures.json").read_text())
GOOD = {k: tuple(v) for k, v in json.loads((FIXTURES / "writer/good_summaries.json").read_text()).items()
        if not k.startswith("_")}
MISC = "38ec41e21301"          # an Events item from Splash247


def payload():
    return copy.deepcopy(PAYLOAD)


def with_change(item_id, summary=None, why=None):
    steps = dict(GOOD)
    old = steps[item_id]
    steps[item_id] = (summary if summary is not None else old[0], why if why is not None else old[1])
    return steps


# ── What the model sees ──────────────────────────────────────────────────────

def test_model_never_sees_figures_or_wire_items():
    items = items_for_model(payload())
    assert {i["id"] for i in items} == set(GOOD)
    assert all(not i.get("excerpt") or not any(c.isdigit() for c in i["excerpt"]) for i in items)
    wire = [i["id"] for i in news_items(payload()) if i.get("wire_agency")]
    assert wire and not set(wire) & {i["id"] for i in items}
    client = FakeClient(GOOD)
    build_brief(payload(), client)
    body = client.requests[0]["messages"][0]["content"]
    assert "125.44" not in body and "display" not in body


def test_request_uses_the_chosen_model_effort_and_json_schema():
    client = FakeClient(GOOD)
    build_brief(payload(), client)
    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5"
    assert request["output_config"]["effort"] == "low"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "No numbers of any kind" in request["system"]


# ── Retry, then withhold ─────────────────────────────────────────────────────

def test_good_summaries_are_published_in_one_call():
    markdown, report = build_brief(payload(), FakeClient(GOOD))
    assert report["published"] and report["writer"]["status"] == "ok"
    assert len(report["writer"]["attempts"]) == 1 and report["writer"]["withheld"] == {}
    assert "Malaysian shipowner MISC has lined up further LNG carriers" in markdown
    assert "**Why it matters (our interpretation):** This suggests" in markdown
    # 3,000 input and 900 output tokens at USD 0.10 / 0.50 per million.
    assert report["writer"]["total_cost_usd"] == pytest.approx(0.00075)


def test_a_failing_summary_is_retried_once_with_the_reason_and_then_accepted():
    bad = with_change(MISC, summary="MISC has lined up 5 more LNG carriers.")
    fixed = {MISC: GOOD[MISC]}
    client = FakeClient(bad, fixed)
    markdown, report = build_brief(payload(), client)
    assert client.sent_ids(1) == [MISC]                        # only the failing item is resent
    assert "contains a digit" in client.requests[1]["messages"][0]["content"]
    assert report["writer"]["status"] == "ok" and MISC in report["writer"]["written"]
    assert "5 more" not in markdown


def test_a_summary_that_fails_twice_is_withheld_and_the_item_shows_headline_and_link():
    bad = with_change(MISC, summary="MISC has lined up two more LNG carriers.")
    client = FakeClient(bad, {MISC: ("MISC has lined up three more LNG carriers.", GOOD[MISC][1])})
    markdown, report = build_brief(payload(), client)
    assert len(client.requests) == 2
    assert report["published"] and report["writer"]["status"] == "partial"
    assert [p["code"] for p in report["writer"]["withheld"][MISC]] == ["number_word"]
    line = next(l for l in markdown.splitlines() if "MISC lines up five more LNG carriers" in l)
    assert "lined up" not in line and "[Read the story](" in line
    assert "This suggests long-term charter demand" not in markdown   # its 'why' is withheld too


def test_a_why_note_stated_as_fact_is_withheld():
    client = FakeClient(with_change(MISC, why="Gas carrier demand is firm."), {MISC: (GOOD[MISC][0], "Demand is firm.")})
    _, report = build_brief(payload(), client)
    assert "not_hedged" in {p["code"] for p in report["writer"]["withheld"][MISC]}


def test_unreadable_model_output_is_retried_then_everything_withheld():
    _, report = build_brief(payload(), FakeClient("garbage", "garbage"))
    assert report["published"] and set(report["writer"]["withheld"]) == set(GOOD)
    assert report["writer"]["attempts"][0]["parse_error"]


# ── Model unavailable: still publish, say why ────────────────────────────────

@pytest.mark.parametrize("error,reason", [
    (FakeAPIError(401, "invalid x-api-key"), "authentication failed"),
    (FakeAPIError(400, "Your credit balance is too low"), "out of credit"),
    (FakeAPIError(429, "rate limited"), "rate limited"),
    (FakeAPIError(529, "overloaded"), "HTTP 529"),
    (ConnectionError("no route"), "could not reach the API"),
])
def test_api_failures_publish_headlines_only_and_report_the_reason(error, reason):
    markdown, report = build_brief(payload(), FakeClient(error))
    assert report["published"]
    assert report["writer"]["status"] == "model_unavailable" and reason in report["writer"]["detail"]
    assert set(report["writer"]["withheld"]) == set(GOOD)
    assert validate_brief(markdown, payload()) == []


def test_a_refusal_publishes_headlines_only():
    _, report = build_brief(payload(), FakeClient("refusal", "refusal"))
    assert report["writer"]["status"] == "model_unavailable"
    assert "declined" in report["writer"]["detail"]


def test_no_key_means_no_model_call():
    markdown, report = build_brief(payload(), None)
    assert report["writer"]["status"] == "no_model" and report["published"]
    assert "no API key configured" in report["writer"]["detail"]


# ── Fail closed on code-level faults ─────────────────────────────────────────

def test_a_renderer_bug_that_changes_a_figure_stops_publication(monkeypatch):
    real = writer.render_brief
    monkeypatch.setattr(writer, "render_brief",
                        lambda *a, **k: real(*a, **k).replace("USD 125.44/bbl", "USD 152.44/bbl"))
    with pytest.raises(BriefRefused) as refused:
        build_brief(payload(), FakeClient(GOOD))
    assert "number_not_in_payload" in {p.code for p in refused.value.problems}


def test_an_out_of_range_payload_figure_stops_publication_before_any_model_call():
    bad = payload()
    bad["sections"]["prices"]["items"][0]["value"] = 999.0
    client = FakeClient(GOOD)
    with pytest.raises(BriefRefused):
        build_brief(bad, client)
    assert client.requests == []                     # nothing spent on a brief that cannot be published


# ── Rendering ────────────────────────────────────────────────────────────────

def test_every_figure_carries_its_date_tag_and_direction_word():
    markdown = render_brief(payload(), {})
    assert ("- **Brent crude oil spot price (FOB Europe):** USD 125.44/bbl, as of 6 October 2026 [S1]. "
            "Down USD 0.07/bbl (0.06%) from 5 October 2026 (previous published day).") in markdown
    assert "for September 2026 [S2]" in markdown


def test_missing_and_not_covered_sections_say_which_and_why():
    p = payload()
    p["sections"]["prices"].update(status="missing", items=[],
                                   reason="EIA request failed: 503 for url: https://api.eia.gov/v2/x?api_key=REDACTED")
    markdown = render_brief(p, {})
    assert "No verified data today: EIA request failed: 503 for url: (address removed)" in markdown
    assert "api_key" not in markdown
    assert "Not covered: No container freight index can be republished" in markdown


def test_same_figure_as_the_previous_brief_is_labelled():
    from modules.morning_brief.validator import figures
    assert render_brief(payload(), {}).count("Same figure as in the previous brief") == 0
    markdown = render_brief(payload(), {}, previous_payload=payload())
    assert markdown.count("Same figure as in the previous brief") == len(figures(payload())) == 19
    newer = payload()
    newer["sections"]["prices"]["items"][0]["as_of"] = "2026-10-07"     # a new Brent value since yesterday
    assert render_brief(newer, {}, previous_payload=payload()).count("Same figure as in the previous brief") == 18


def test_feed_text_cannot_inject_markdown():
    p = payload()
    item = next(i for i in news_items(p) if i["id"] == MISC)
    item["headline"] = "Owner *orders* [ships](https://evil.example) # now"
    markdown = render_brief(p, {})
    assert "\\[ships\\]" in markdown            # escaped, so not a link
    assert check_numbers(markdown, p) == []


def test_data_sources_carry_a_retrieval_date_for_the_licence_notice():
    markdown = render_brief(payload(), {})
    line = next(l for l in markdown.splitlines() if l.startswith("- [S2]"))
    assert "Singapore Open Data Licence version 1.0" in line and "Retrieved for this brief on 12 October 2026" in line


# ── Command-line tools ───────────────────────────────────────────────────────

def run(*args, env=None):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT), **(env or {})})


def test_write_cli_without_a_key_publishes_headlines_only(tmp_path):
    result = run("-m", "modules.morning_brief.write", "--payload", str(FIXTURES / "payload/from_fixtures.json"),
                 "--out-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "validation.json").read_text())
    assert report["published"] and report["writer"]["status"] == "no_model"
    assert (tmp_path / "brief.md").read_text().startswith("# BrokerBrief Morning Brief: 12 October 2026")
    assert report["section_status"]["freight.container_rates"] == "not_covered"


def test_write_cli_refuses_and_writes_no_brief(tmp_path):
    bad = payload()
    bad["sections"]["prices"]["items"][0]["value"] = 999.0
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    result = run("-m", "modules.morning_brief.write", "--payload", str(path), "--out-dir", str(tmp_path / "out"))
    assert result.returncode == 3
    assert not (tmp_path / "out" / "brief.md").exists()
    report = json.loads((tmp_path / "out" / "validation.json").read_text())
    assert not report["published"] and report["refused_because"][0]["code"] == "out_of_range"


def test_validate_cli_catches_every_must_fail_case():
    result = run("-m", "modules.morning_brief.validate", "--cases", str(FIXTURES / "validator"))
    assert result.returncode == 0, result.stdout
    assert "18 of 18 must-fail cases caught" in result.stdout


def test_validate_cli_fails_if_a_must_fail_case_slips_through(tmp_path):
    case = json.loads((FIXTURES / "validator/02_number_not_in_payload.json").read_text())
    case["brief_replace"] = []                       # nothing wrong with the brief any more
    (tmp_path / "slipped.json").write_text(json.dumps(case))
    ok, rows = run_cases(tmp_path)
    assert not ok and rows[0][2] == "passed"


def test_model_trial_reports_pass_rate_and_cost_without_the_network():
    from modules.morning_brief.model_trial import trial
    bad_then_good = with_change(MISC, summary="MISC has lined up 5 more LNG carriers.")
    client = FakeClient(GOOD, bad_then_good, {MISC: GOOD[MISC]})
    result = trial(client, "claude-haiku-5-5", 2, payload())
    assert result["published"] == 2 and result["passes"] and result["withheld"] == 0
    assert result["after_retry"] == 1 and result["first_try"] == 2 * len(GOOD) - 1
    assert result["cost_per_brief_usd"] == pytest.approx(0.00075 * 3 / 2)



# ── Fixes from the Phase 2 review (12-11-2026) ───────────────────────────────

def publishes(p, client=None):
    markdown, report = build_brief(p, client or FakeClient(GOOD))
    return markdown, report


def test_ordinary_feed_content_never_stops_the_brief():
    p = payload()
    items = {i["id"]: i for i in news_items(p)}
    items[MISC]["author"] = "Hans ten Cate"                       # a number word in a name
    items["e8fd72eddcea"]["author"] = "Staff 2"                   # a digit in a name
    items["dc19c507a379"]["headline"] = "Owners rush to order *"  # trailing Markdown character
    items["64fa131aa297"]["headline"] = "Ship <b>names</b> & owners: a [list]"
    p["sections"]["prices"].update(status="missing", items=[],
                                   reason="EIA request failed for url: https://cdn123.example456.net/x?api_key=REDACTED")
    markdown, report = publishes(p)
    assert report["published"] and validate_brief(markdown, p) == []
    assert "cdn123" not in markdown


def test_unsafe_links_and_urls_in_headlines_are_dropped_at_fetch_time():
    from datetime import datetime, timezone
    from modules.morning_brief.news import build_item
    now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    base = {"title": "Owners order new ships", "link": "https://gcaptain.com/story/", "published": now,
            "categories": [], "excerpt_html": "Some words.", "author": "", "credit_fields": []}
    assert build_item(base, "gcaptain", now)[0] is not None
    assert build_item({**base, "link": "https://example.org/wiki/Ever_Given_(ship)"}, "gcaptain", now)[1] == "unsafe_link"
    assert build_item({**base, "link": "https://gcaptain.com/a b"}, "gcaptain", now)[1] == "unsafe_link"
    assert build_item({**base, "title": "Read more at https://x.org"}, "gcaptain", now)[1] == "link_in_headline"
    assert build_item({**base, "title": "See www.example.com today"}, "gcaptain", now)[1] == "link_in_headline"


def test_a_section_marked_ok_with_no_items_is_refused_not_published_blank():
    p = payload()
    p["sections"]["events"]["items"] = []
    with pytest.raises(BriefRefused) as refused:
        build_brief(p, FakeClient(GOOD))
    assert "ok_but_empty" in {x.code for x in refused.value.problems}


def test_silent_gap_check_works_on_real_rendered_output():
    p = payload()
    markdown = render_brief(p, {})
    gutted = markdown.replace(
        next(l for l in markdown.splitlines() if l.startswith("- **Capesize rates climb")) + "\n", "")
    assert "silent_gap" in {x.code for x in validate_brief(gutted, p)}


def test_swapped_figure_values_are_caught():
    markdown = render_brief(payload(), {})
    swapped = (markdown.replace("302 transits, as of", "TMP, as of")
               .replace("190 transits, as of", "302 transits, as of").replace("TMP, as of", "190 transits, as of"))
    codes = {x.code for x in validate_brief(swapped, payload())}
    assert "figure_missing" in codes


def test_refusal_then_success_is_ok_not_unavailable():
    _, report = publishes(payload(), FakeClient("refusal", GOOD))
    assert report["writer"]["status"] == "ok" and report["writer"]["withheld"] == {}


def test_error_on_the_retry_after_a_partial_success_is_partial_with_the_reason():
    first = with_change(MISC, summary="MISC has lined up 5 more LNG carriers.")
    _, report = publishes(payload(), FakeClient(first, FakeAPIError(529, "overloaded")))
    writer_report = report["writer"]
    assert writer_report["status"] == "partial" and list(writer_report["withheld"]) == [MISC]
    assert "HTTP 529" in writer_report["detail"]


def test_unreadable_output_twice_is_unavailable_with_the_reason():
    _, report = publishes(payload(), FakeClient("garbage", "garbage"))
    assert report["writer"]["status"] == "model_unavailable"
    assert "could not be read" in report["writer"]["detail"]


def test_permission_denied_is_reported():
    _, report = publishes(payload(), FakeClient(FakeAPIError(403, "forbidden")))
    assert "permission denied" in report["writer"]["detail"]


def test_a_bug_in_our_code_is_not_reported_as_an_api_outage():
    with pytest.raises(TypeError):
        publishes(payload(), FakeClient(TypeError("unexpected keyword argument")))


def test_numeric_symbols_and_fold_words_are_refused_in_summaries():
    from modules.morning_brief.validator import check_summary
    item = {"id": "x", "headline": "h", "excerpt": ""}
    for text in ("Orders rose by ½.", "Volumes rose tenfold.", "Volumes rose ten-fold.", "Output rose twice over.",
                 "A rise of five %.", "Ⅻ ships were ordered.", "Contact press@example.com for more.",
                 "Details are at example.com today."):
        assert check_summary(text, item), text


def test_archived_payload_carries_no_publisher_excerpts(tmp_path):
    result = run("-m", "modules.morning_brief.write", "--payload", str(FIXTURES / "payload/from_fixtures.json"),
                 "--out-dir", str(tmp_path))
    assert result.returncode == 0
    archived = json.loads((tmp_path / "payload.json").read_text())
    assert all("excerpt" not in i for i in news_items(archived))
    assert any(i.get("excerpt") for i in news_items(PAYLOAD))       # the input did have them


def test_a_refused_run_removes_an_old_brief_from_the_folder(tmp_path):
    (tmp_path / "brief.md").write_text("yesterday's brief")
    bad = payload()
    bad["sections"]["prices"]["items"][0]["value"] = 999.0
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    assert run("-m", "modules.morning_brief.write", "--payload", str(path), "--out-dir", str(tmp_path)).returncode == 3
    assert not (tmp_path / "brief.md").exists()


def test_model_trial_does_not_count_an_api_error_as_first_try_success():
    from modules.morning_brief.model_trial import trial
    result = trial(FakeClient(FakeAPIError(401, "bad key")), "claude-haiku-5-5", 1, payload())
    assert result["first_try"] == 0 and result["after_retry"] == 0 and not result["passes"]


def test_request_serialises_through_the_real_sdk_and_a_real_message_parses():
    """The fake client returns plain objects; this sends the real request body
    through the installed anthropic SDK with a mock HTTP transport, and parses
    a real Message that has a thinking block before the text block."""
    anthropic = pytest.importorskip("anthropic")
    import httpx2 as httpx
    seen = {}
    body = {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 800},
            "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                        {"type": "text", "text": json.dumps({"items": [
                            {"id": k, "summary": v[0], "why_it_matters": v[1]} for k, v in GOOD.items()]})}]}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=body)

    client = anthropic.Anthropic(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    markdown, report = build_brief(payload(), client)
    assert seen["body"]["model"] == "claude-haiku-5-5"
    assert seen["body"]["output_config"]["format"]["type"] == "json_schema"
    assert report["writer"]["status"] == "ok" and len(report["writer"]["written"]) == len(GOOD)
