"""
tests/test_morning_brief_automation.py

Phase 3 pieces that run unattended: the archive, the alert decision, the
static site, the failure-test hook and the workflow file. No network.
"""

import copy
import json
from pathlib import Path

import pytest
import requests

from modules.morning_brief import archive, site
from modules.morning_brief.alerts import EMPTY_DAYS_ALERT, decide
from modules.morning_brief.guarded_http import guarded_get
from modules.morning_brief.writer import build_brief
from tests.fake_model import FakeClient
from tests.fixture_http import FIXTURES

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = json.loads((FIXTURES / "payload/from_fixtures.json").read_text())
GOOD = {k: tuple(v) for k, v in json.loads((FIXTURES / "writer/good_summaries.json").read_text()).items()
        if not k.startswith("_")}


def run_output(tmp_path, brief_date, *, published=True, missing=(), name="out"):
    """A writer output folder as the workflow produces it."""
    p = copy.deepcopy(PAYLOAD)
    p["brief_date"] = brief_date
    out = tmp_path / f"{name}-{brief_date}"
    out.mkdir()
    (out / "payload.json").write_text(json.dumps(p))
    sections = {"prices": "ok", "bunker_sales": "ok", "events": "ok", "freight.container_rates": "not_covered"}
    sections.update({m: "missing" for m in missing})
    report = {"brief_date": brief_date, "published": published, "section_status": sections,
              "writer": {"status": "ok", "withheld": {}, "total_cost_usd": 0.001}}
    if published:
        (out / "brief.md").write_text(f"# BrokerBrief Morning Brief: {brief_date}\n\nBody <script>alert(1)</script>\n")
    else:
        report["refused_because"] = [{"code": "number_not_in_payload"}]
    (out / "validation.json").write_text(json.dumps(report))
    return out


# ── Archive ──────────────────────────────────────────────────────────────────

def test_store_writes_the_day_folder_index_and_health(tmp_path):
    root = tmp_path / "archive"
    archive.store(root, run_output(tmp_path, "2026-11-12"), {"run_url": "https://example.org/run/1"})
    folder = root / "briefs/2026/11/12"
    assert sorted(p.name for p in folder.iterdir()) == ["brief.md", "payload.json", "validation.json"]
    index = archive.read_index(root)
    assert index[0]["date"] == "2026-11-12" and index[0]["published"] and index[0]["run_url"].endswith("/1")
    assert archive.has_brief(root, "2026-11-12")


def test_rerunning_a_date_replaces_it_instead_of_duplicating(tmp_path):
    root = tmp_path / "archive"
    archive.store(root, run_output(tmp_path, "2026-11-12", published=False))
    assert not archive.has_brief(root, "2026-11-12")
    archive.store(root, run_output(tmp_path, "2026-11-12", name="again"))
    assert [e["date"] for e in archive.read_index(root)] == ["2026-11-12"]
    assert archive.has_brief(root, "2026-11-12")


def test_empty_streaks_count_consecutive_days_and_ignore_not_covered(tmp_path):
    root = tmp_path / "archive"
    for day, missing in (("2026-11-09", ()), ("2026-11-10", ("prices",)), ("2026-11-11", ("prices",)),
                         ("2026-11-12", ("prices", "events"))):
        archive.store(root, run_output(tmp_path, day, missing=missing))
    health = json.loads((root / archive.HEALTH).read_text())
    assert health["empty_streak_days"]["prices"] == 3
    assert health["empty_streak_days"]["events"] == 1
    assert health["empty_streak_days"]["freight.container_rates"] == 0


def test_previous_payload_is_the_latest_published_one_before_the_date(tmp_path):
    root = tmp_path / "archive"
    archive.store(root, run_output(tmp_path, "2026-11-10"))
    archive.store(root, run_output(tmp_path, "2026-11-11", published=False))
    assert archive.latest_payload(root, "2026-11-12") == root / "briefs/2026/11/10/payload.json"
    assert archive.latest_payload(root, "2026-11-10") is None


# ── Alert decision ───────────────────────────────────────────────────────────

def report(**overrides):
    base = {"brief_date": "2026-11-12", "published": True, "writer": {"status": "ok"}}
    base.update(overrides)
    return base


def test_clean_run_clears():
    d = decide(outcome="success", report=report(), health={"empty_streak_days": {"prices": 2}}, expect_model=True)
    assert d["action"] == "clear" and d["reasons"] == []


def test_a_failed_step_alerts_and_names_it():
    d = decide(outcome="failure", report=None, health=None, expect_model=True, failed_step="Build the payload",
               run_url="https://example.org/run/7")
    assert d["action"] == "alert" and "Build the payload" in d["body"] and "run/7" in d["body"]


def test_a_refused_brief_alerts_with_the_codes():
    d = decide(outcome="success", report=report(published=False, refused_because=[{"code": "out_of_range"}]),
               health=None, expect_model=False)
    assert d["action"] == "alert" and "out_of_range" in d["body"]


def test_an_unreachable_model_alerts_only_when_a_key_is_configured():
    r = report(writer={"status": "model_unavailable", "detail": "authentication failed (API key missing, wrong or revoked)"})
    assert decide(outcome="success", report=r, health=None, expect_model=True)["action"] == "alert"
    assert decide(outcome="success", report=r, health=None, expect_model=False)["action"] == "clear"


def test_a_section_empty_for_three_days_alerts():
    health = {"empty_streak_days": {"prices": EMPTY_DAYS_ALERT, "events": EMPTY_DAYS_ALERT - 1}}
    d = decide(outcome="success", report=report(), health=health, expect_model=True)
    assert d["action"] == "alert" and len(d["reasons"]) == 1 and "`prices`" in d["body"]


# ── Site ─────────────────────────────────────────────────────────────────────

def built_site(tmp_path, *days):
    root = tmp_path / "archive"
    for day in days:
        archive.store(root, run_output(tmp_path, day))
    readme = tmp_path / "README.md"
    readme.write_text("# BrokerBrief\n\nLanding text.\n")
    out = tmp_path / "_site"
    site.build(root, readme, out)
    return out


def test_site_has_landing_latest_archive_and_each_brief(tmp_path):
    out = built_site(tmp_path, "2026-11-11", "2026-11-12")
    assert (out / ".nojekyll").exists()
    latest = (out / "brief/index.html").read_text()
    assert "Last updated: 12 November 2026" in latest and "Trial — under review" in latest
    assert (out / "brief/2026-11-11.html").exists()
    assert "Landing text." in (out / "index.html").read_text()
    assert "12 November 2026" in (out / "brief/archive.html").read_text()


def test_raw_html_in_a_brief_is_shown_as_text_not_run(tmp_path):
    latest = (built_site(tmp_path, "2026-11-12") / "brief/index.html").read_text()
    assert "<script>alert(1)</script>" not in latest
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in latest


def test_brief_pages_carry_a_staleness_banner_for_readers(tmp_path):
    latest = (built_site(tmp_path, "2026-11-12") / "brief/index.html").read_text()
    assert 'id="stale"' in latest and 'data-generated="2026-11-12"' in latest
    assert "has not been updated for more than two days" in latest


def test_site_with_no_brief_yet_says_so(tmp_path):
    out = built_site(tmp_path)
    assert "No brief has been published yet" in (out / "brief/index.html").read_text()


def test_a_real_brief_renders_with_working_links(tmp_path):
    markdown, _ = build_brief(copy.deepcopy(PAYLOAD), FakeClient(GOOD))
    html = site.brief_page(markdown, "2026-10-12")
    assert '<a href="https://splash247.com/tanker-war-spreads-across-gulf/">Read the story</a>' in html
    assert "<h2>1. Prices</h2>" in html


# ── Failure-test hook ────────────────────────────────────────────────────────

def test_break_feed_makes_only_that_source_fail(monkeypatch):
    monkeypatch.setenv("BROKERBRIEF_BREAK_FEED", "gcaptain")
    with pytest.raises(requests.ConnectionError, match="deliberately broken"):
        guarded_get("https://gcaptain.com/feed/")


def test_break_feed_end_to_end_marks_the_section_missing_with_the_reason(monkeypatch):
    from modules.morning_brief.payload import fetch_and_build
    from tests.test_morning_brief_payload import NOW, getter
    monkeypatch.setenv("BROKERBRIEF_BREAK_FEED", "mpa_bunker_sales")
    from modules.morning_brief import guarded_http
    real_get = getter()
    def get(url, params=None, timeout=None, **kw):
        guarded_http.check_break(url)                 # the hook guarded_get applies
        return real_get(url, params=params, timeout=timeout, **kw)
    payload = fetch_and_build(now=NOW, eia_api_key="key", get=get)
    section = payload["sections"]["bunker_sales"]
    assert section["status"] == "missing" and "deliberately broken" in section["reason"]
    assert payload["sections"]["prices"]["status"] == "ok"


# ── Workflow file ────────────────────────────────────────────────────────────

def test_workflow_has_no_schedule_until_batch_three_and_safe_permissions():
    """Checked as text: the schedule must not be live until Decision Batch 3,
    and each job gets only the permissions it needs."""
    import re
    text = (ROOT / ".github/workflows/morning-brief.yml").read_text()
    live = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    assert not any(re.match(r"\s*schedule:", l) for l in live), "schedule must stay off until Batch 3"
    assert any(re.match(r"\s*workflow_dispatch:", l) for l in live)
    brief_job = text[text.index("  brief:"):text.index("  site:")]
    assert re.search(r"permissions:\n\s+contents: write.*\n\s+issues: write.*\n\s+actions: write", brief_job)
    site_job = text[text.index("  site:"):]
    assert re.search(r"permissions:\n\s+contents: read\n\s+pages: write\n\s+id-token: write\n\s+issues: write", site_job)
    assert "Alert if publishing failed" in site_job and "if: failure()" in site_job
    assert "secrets.ANTHROPIC_API_KEY" in text and not re.search(r"echo[^\n]*secrets\.", text)
    assert "path: work/out/" in text          # the artifact never holds the excerpts
