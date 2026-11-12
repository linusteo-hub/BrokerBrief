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

from datetime import date

TODAY = date(2026, 11, 13)
ALL_OK = {"keepalive": "success", "build": "success", "archive": "success", "site": "success"}


def report(**overrides):
    base = {"brief_date": "2026-11-13", "published": True, "writer": {"status": "ok"}}
    base.update(overrides)
    return base


def scheduled(**kw):
    args = dict(jobs=dict(ALL_OK), report=report(), health={"empty_streak_days": {}}, latest_archived="2026-11-13",
                today=TODAY, scheduled=True, has_model_key=True, no_model=False, archived=True)
    args.update(kw)
    return decide(**args)


def test_clean_scheduled_run_clears_the_real_label():
    d = scheduled()
    assert d["action"] == "clear" and d["reasons"] == [] and d["label"] == "brief-alert"


def test_any_failed_or_cancelled_job_alerts_and_names_it():
    for job, result in (("archive", "failure"), ("site", "failure"), ("build", "cancelled"), ("keepalive", "failure")):
        d = scheduled(jobs={**ALL_OK, job: result})
        assert d["action"] == "alert", (job, result)
    assert "was cancelled or timed out" in scheduled(jobs={**ALL_OK, "build": "cancelled"}, report=None)["body"]
    assert "Archive to the briefs branch" in scheduled(jobs={**ALL_OK, "archive": "failure"})["body"]


def test_a_refused_brief_alerts_with_the_codes():
    d = scheduled(report=report(published=False, refused_because=[{"code": "out_of_range"}]))
    assert d["action"] == "alert" and "out_of_range" in d["body"]


def test_a_crashed_writer_is_reported_as_a_crash_not_a_refusal():
    d = scheduled(report=report(published=False, crashed="KeyError: 'sections'"))
    assert "crashed" in d["body"] and "KeyError" in d["body"] and "gate refused" not in d["body"]


def test_build_success_without_a_report_alerts():
    assert scheduled(report=None)["action"] == "alert"


def test_scheduled_runs_always_expect_the_model_even_if_the_secret_vanished():
    r = report(writer={"status": "no_model", "detail": "no API key configured"})
    assert scheduled(report=r, has_model_key=False)["action"] == "alert"
    manual = scheduled(report=r, has_model_key=False, scheduled=False)
    assert manual["action"] == "clear"                     # a manual run without a key is a choice


def test_a_section_empty_for_three_run_dates_alerts_only_once_archived():
    health = {"empty_streak_days": {"prices": EMPTY_DAYS_ALERT, "events": EMPTY_DAYS_ALERT - 1}}
    d = scheduled(health=health)
    assert d["action"] == "alert" and len(d["reasons"]) == 1 and "`prices`" in d["body"]
    assert scheduled(health=health, archived=False)["action"] == "clear"


def test_a_missed_day_alerts():
    assert scheduled(latest_archived="2026-11-12")["action"] == "clear"
    d = scheduled(latest_archived="2026-11-11")
    assert d["action"] == "alert" and "No brief has been archived since 2026-11-11" in d["body"]


def test_manual_runs_use_a_separate_label_so_they_never_close_a_real_alert():
    d = scheduled(scheduled=False, archived=False)
    assert d["label"] == "brief-alert-test" and "(manual run)" in d["title"]


def test_a_failure_test_always_opens_a_test_alert():
    d = scheduled(scheduled=False, archived=False, break_feed="mpa_bunker_sales")
    assert d["action"] == "alert" and d["label"] == "brief-alert-test"
    assert "`mpa_bunker_sales` was broken on purpose" in d["body"]


def test_alerts_command_reads_the_workflow_job_results(tmp_path):
    import subprocess, sys
    needs = json.dumps({"keepalive": {"result": "success", "outputs": {}}, "build": {"result": "failure", "outputs": {}},
                        "archive": {"result": "skipped", "outputs": {}}, "site": {"result": "skipped", "outputs": {}}})
    result = subprocess.run([sys.executable, "-m", "modules.morning_brief.alerts", "--archive", str(tmp_path),
                             "--report", str(tmp_path / "absent.json"), "--jobs-json", needs, "--scheduled", "true"],
                            cwd=ROOT, capture_output=True, text=True)
    decision = json.loads(result.stdout)
    assert decision["action"] == "alert" and "Build and write the brief" in decision["body"]


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
    latest = (out / "brief/index.html").read_text()
    assert "Last updated: 12 November 2026" in latest and "Trial — under review" in latest
    assert (out / "brief/2026-11-11.html").exists()
    assert "Landing text." in (out / "index.html").read_text()
    assert "12 November 2026" in (out / "brief/archive.html").read_text()


def test_raw_html_in_a_brief_is_shown_as_text_not_run(tmp_path):
    latest = (built_site(tmp_path, "2026-11-12") / "brief/index.html").read_text()
    assert "<script>alert(1)</script>" not in latest
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in latest


def test_only_the_latest_brief_carries_the_staleness_banner(tmp_path):
    out = built_site(tmp_path, "2026-11-11", "2026-11-12")
    latest = (out / "brief/index.html").read_text()
    assert 'id="stale"' in latest and 'data-generated="2026-11-12"' in latest
    assert "has not been updated for more than two days" in latest
    assert 'id="stale"' not in (out / "brief/2026-11-11.html").read_text()
    assert "T06:00:00+08:00" in latest and "age>2" in latest          # two days from 06:00 Singapore time


def test_relative_links_work_from_every_page(tmp_path):
    out = built_site(tmp_path, "2026-11-12")
    assert 'href="brief/index.html"' in (out / "index.html").read_text()
    for page_name in ("brief/index.html", "brief/2026-11-12.html", "brief/archive.html"):
        text = (out / page_name).read_text()
        assert 'href="../index.html"' in text and 'href="../brief/archive.html"' in text, page_name


def test_public_archive_table_uses_plain_words(tmp_path):
    root = tmp_path / "archive"
    out_dir = run_output(tmp_path, "2026-11-12")
    data = json.loads((out_dir / "validation.json").read_text())
    data["writer"]["status"] = "no_model"
    (out_dir / "validation.json").write_text(json.dumps(data))
    archive.store(root, out_dir)
    readme = tmp_path / "README.md"; readme.write_text("# x\n")
    site.build(root, readme, tmp_path / "_site")
    table = (tmp_path / "_site/brief/archive.html").read_text()
    assert "headlines only (no model configured)" in table and "no_model" not in table


def test_site_with_no_brief_yet_says_so(tmp_path):
    out = built_site(tmp_path)
    assert "No brief has been published yet" in (out / "brief/index.html").read_text()


def test_a_real_brief_renders_with_working_links(tmp_path):
    markdown, _ = build_brief(copy.deepcopy(PAYLOAD), FakeClient(GOOD))
    html = site.brief_page(markdown, "2026-10-12", latest=True)
    assert '<a href="https://splash247.com/tanker-war-spreads-across-gulf/">Read the story</a>' in html
    assert "<h2>1. Prices</h2>" in html


# ── Failure-test hook ────────────────────────────────────────────────────────

def test_break_feed_makes_only_that_source_fail(monkeypatch):
    monkeypatch.setenv("BROKERBRIEF_BREAK_FEED", "gcaptain")
    with pytest.raises(requests.ConnectionError, match="deliberately broken"):
        guarded_get("https://gcaptain.com/feed/")


def test_break_feed_none_or_unset_is_inert(monkeypatch):
    from modules.morning_brief.guarded_http import check_break
    for value in ("none", "", " "):
        monkeypatch.setenv("BROKERBRIEF_BREAK_FEED", value)
        check_break("https://gcaptain.com/feed/")                       # no exception
    monkeypatch.delenv("BROKERBRIEF_BREAK_FEED")
    check_break("https://gcaptain.com/feed/")


def test_break_feed_end_to_end_through_guarded_get(monkeypatch):
    """The real guarded_get, with requests.get stubbed to serve fixtures: the
    broken source's section is published as missing with the reason."""
    from modules.morning_brief.payload import fetch_and_build
    from tests.test_morning_brief_payload import NOW, getter
    serve = getter()
    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=None, headers=None, allow_redirects=True:
                        type("R", (), {**vars(serve(url, params=params, timeout=timeout)).copy(), "is_redirect": False,
                                       "raise_for_status": serve(url, params=params).raise_for_status,
                                       "json": serve(url, params=params).json})())
    monkeypatch.setenv("BROKERBRIEF_BREAK_FEED", "mpa_bunker_sales")
    payload = fetch_and_build(now=NOW, eia_api_key="key")
    section = payload["sections"]["bunker_sales"]
    assert section["status"] == "missing"
    assert "mpa_bunker_sales deliberately broken for a failure test" in section["reason"]
    assert payload["sections"]["prices"]["status"] == "ok"


def test_breaking_one_news_feed_leaves_the_section_with_the_other_publishers(monkeypatch):
    """As docs/operations.md says: a news section is marked missing only when
    every feed fails; one broken feed is recorded in the validation report."""
    from modules.morning_brief.payload import fetch_and_build
    from modules.morning_brief.guarded_http import check_break
    from tests.test_morning_brief_payload import NOW, getter
    serve = getter()
    def get(url, params=None, timeout=None, **kw):
        check_break(url)
        return serve(url, params=params, timeout=timeout)
    monkeypatch.setenv("BROKERBRIEF_BREAK_FEED", "gcaptain")
    payload = fetch_and_build(now=NOW, eia_api_key="key", get=get)
    assert payload["sections"]["events"]["status"] == "ok"
    assert "deliberately broken" in payload["validation"]["feed_errors"]["gcaptain"]


# ── Workflow file ────────────────────────────────────────────────────────────

def _job(text: str, name: str) -> str:
    import re
    start = text.index(f"\n  {name}:\n")
    nxt = re.search(r"\n  [a-z]+:\n", text[start + 1:])
    return text[start: start + 1 + nxt.start()] if nxt else text[start:]


def test_workflow_has_no_schedule_until_batch_three():
    import re
    text = (ROOT / ".github/workflows/morning-brief.yml").read_text()
    live = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    assert not any(re.match(r"\s*schedule:", l) for l in live), "schedule must stay off until Batch 3"
    assert any(re.match(r"\s*workflow_dispatch:", l) for l in live)


def test_each_job_has_only_the_permissions_it_needs():
    text = (ROOT / ".github/workflows/morning-brief.yml").read_text()
    expected = {
        "keepalive": ["actions: write"],
        "build": ["contents: read"],
        "archive": ["contents: write"],
        "site": ["contents: read", "pages: write", "id-token: write"],
        "alert": ["contents: read", "issues: write"],
    }
    import re
    for job, perms in expected.items():
        block = _job(text, job)
        found = re.search(r"permissions:\n((?:\s{6}[a-z-]+: \w+.*\n)+)", block).group(1)
        assert [l.split("#")[0].strip() for l in found.strip().splitlines()] == perms, job
    # The job holding the API keys cannot push, and does not keep a token on disk.
    build = _job(text, "build")
    assert "secrets.ANTHROPIC_API_KEY" in build and "persist-credentials: false" in build
    assert "secrets." not in _job(text, "archive") and "secrets." not in _job(text, "site")


def test_workflow_never_hides_a_failure():
    text = (ROOT / ".github/workflows/morning-brief.yml").read_text()
    alert = _job(text, "alert")
    assert "needs: [keepalive, build, archive, site]" in alert and "if: always()" in alert
    archive_job = _job(text, "archive")
    assert '[ -n "$pushed" ] ||' in archive_job
    for job in ("build", "archive"):
        assert "elif [ \"$code\" -eq 2 ]" in _job(text, job) and "exit 1" in _job(text, job)
    assert "|| mkdir -p archive" not in _job(text, "site")           # never deploy an empty site
    assert "path: work/out/" in _job(text, "build")                    # the artifact never holds excerpts
    assert "inputs.break_feed == 'none'" in archive_job and "inputs.break_feed == 'none'" in _job(text, "site")


def _push_loop() -> str:
    text = (ROOT / ".github/workflows/morning-brief.yml").read_text()
    archive_job = _job(text, "archive")
    start = archive_job.index('pushed=""')
    end = archive_job.index("\n", archive_job.index('[ -n "$pushed" ]'))
    return "\n".join(line.strip() for line in archive_job[start:end].splitlines())


@pytest.mark.parametrize("push_succeeds_on,expected_exit", [(None, 1), (1, 0), (3, 0)])
def test_archive_push_loop_fails_the_step_only_when_every_push_fails(tmp_path, push_succeeds_on, expected_exit):
    """Runs the workflow's own push loop under bash -e with a stand-in git:
    the step must fail if all four pushes fail (it once passed silently)."""
    import subprocess
    fake = f"""
attempt=0
git() {{
  if [ "$1" = push ]; then attempt=$((attempt+1)); [ "{push_succeeds_on or 99}" -le "$attempt" ]; return; fi
  return 1     # pull --rebase and rebase --abort also fail, the worst case
}}
sleep() {{ :; }}
"""
    script = tmp_path / "loop.sh"
    script.write_text("set -e\n" + fake + _push_loop() + "\n")
    result = subprocess.run(["bash", "-e", "-o", "pipefail", str(script)], capture_output=True, text=True)
    assert result.returncode == expected_exit, result.stdout + result.stderr
