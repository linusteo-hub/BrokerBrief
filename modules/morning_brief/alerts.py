"""
modules/morning_brief/alerts.py

Decides whether a run needs Linus's attention. The workflow's last job runs
whatever happened, passes every other job's result here, and acts on the
decision with the GitHub CLI: one open issue per label at a time, a comment on
it for each further problem day, closed by the next clean run.

Labels: scheduled runs use `brief-alert`. Manual runs use `brief-alert-test`,
so a test can never close or clutter a real alert.

Alert when:
- any job failed, was cancelled or timed out (a crash, a network error in our
  own code, a failed push or deploy);
- the gate refused the brief, or the writer crashed (nothing was published);
- the model is switched on (BRIEF_USE_MODEL) but the writer could not use it
  (a deleted or mistyped secret counts). With the model off, which is the
  default, headline-only news is the normal state and raises nothing;
- a section has been empty on EMPTY_DAYS_ALERT consecutive run dates;
- the archive has no entry for yesterday (both scheduled runs dropped, or
  failed before archiving), once the archive is older than that;
- the archive could not be read;
- a failure test: the broken source is reported, to prove the alert path.

A run that skipped because today's brief already exists (the fallback after
a good primary run) decides "none": it neither alerts nor clears, so it can
never reopen or close what the primary run decided.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from modules.morning_brief.archive import HEALTH, read_index

EMPTY_DAYS_ALERT = 3
LABEL, TEST_LABEL = "brief-alert", "brief-alert-test"
TITLE = "Morning brief needs attention"
SGT = timezone(timedelta(hours=8))
JOB_NAMES = {"keepalive": "Keep the schedules alive", "build": "Build and write the brief",
             "archive": "Archive to the briefs branch", "site": "Publish to GitHub Pages"}


def decide(*, jobs: dict, report: Optional[dict], health: Optional[dict], archive_dates: list,
           today: date, scheduled: bool, use_model: bool, no_model: bool, break_feed: str = "none",
           archived: bool = False, skipped: bool = False, archive_readable: bool = True,
           run_url: str = "") -> dict:
    test = not scheduled
    label, title = (TEST_LABEL, TITLE + " (manual run)") if test else (LABEL, TITLE)
    failed_jobs = [j for j, r in jobs.items() if r in ("failure", "cancelled")]
    if skipped and not failed_jobs and archive_readable:
        return {"action": "none", "label": label, "title": title, "reasons": [],
                "body": "Skipped: today's brief already exists."}
    reasons = []
    for job, result in jobs.items():
        if result in ("failure", "cancelled"):
            reasons.append(f"Job \"{JOB_NAMES.get(job, job)}\" {'was cancelled or timed out' if result == 'cancelled' else 'failed'}. "
                           "Open the run to see the step.")
    if not archive_readable:
        reasons.append("The alert job could not read the briefs branch, so the archive checks below were not made.")
    build_ran = jobs.get("build") == "success" and not skipped
    if build_ran and report is None:
        reasons.append("The build finished but left no validation report.")
    if report is not None and report.get("crashed"):
        reasons.append(f"The writer crashed, so nothing was published: {report['crashed']}")
    elif report is not None and not report.get("published"):
        codes = sorted({p["code"] for p in report.get("refused_because", [])})
        reasons.append("The publishing gate refused the brief, so nothing was published. Problem codes: "
                       + (", ".join(codes) or "none recorded") + ". This points to a bug in BrokerBrief's code.")
    writer = (report or {}).get("writer") or {}
    model_expected = use_model and not no_model
    if model_expected and writer.get("status") in ("model_unavailable", "no_model"):
        reasons.append(f"The writer could not use the model: {writer.get('detail') or writer.get('status')}. "
                       "News went out as headline and link only. Check the ANTHROPIC_API_KEY secret, the key, "
                       "and credit (docs/operations.md, \"Language model (off)\").")
    if archived:
        for section, days in sorted(((health or {}).get("empty_streak_days") or {}).items()):
            if days >= EMPTY_DAYS_ALERT:
                reasons.append(f"Section `{section}` has been empty on {days} run dates in a row. "
                               "Its reason is in the latest brief and in validation.json.")
    # A gap in the archive: no entry for yesterday, although the archive began
    # before yesterday. (Today's entry was just written by this run, so the
    # gap is looked for one day back.)
    yesterday = (today - timedelta(days=1)).isoformat()
    if scheduled and archive_readable and archive_dates and min(archive_dates) < yesterday \
            and yesterday not in archive_dates:
        reasons.append(f"No run was archived for {yesterday}: both scheduled runs were dropped, or failed "
                       "before archiving. That day has no brief.")
    if break_feed and break_feed != "none":
        reasons.append(f"Failure test: `{break_feed}` was broken on purpose. Check that the brief marks its "
                       "data as missing with the reason, and that this issue appeared. This run was not archived "
                       "or published.")

    lines = [f"- {r}" for r in reasons]
    if report is not None and report.get("brief_date"):
        lines.insert(0, f"Brief date: {report['brief_date']}\n")
    if run_url:
        lines.append(f"\nRun: {run_url}")
    return {"action": "alert" if reasons else "clear", "label": label, "title": title,
            "reasons": reasons, "body": "\n".join(lines)}


def _flag(value: str) -> bool:
    return str(value).strip().lower() == "true"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.alerts")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--report")
    parser.add_argument("--jobs-json", default="{}", help="the workflow's toJSON(needs)")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--scheduled", default="false")
    parser.add_argument("--use-model", default="false")
    parser.add_argument("--no-model", default="false")
    parser.add_argument("--break-feed", default="none")
    parser.add_argument("--archived", default="false")
    parser.add_argument("--archive-readable", default="true")
    args = parser.parse_args(argv)

    needs = json.loads(args.jobs_json or "{}")
    jobs = {name: info.get("result") if isinstance(info, dict) else info for name, info in needs.items()}
    build_outputs = (needs.get("build") or {}).get("outputs") or {} if isinstance(needs.get("build"), dict) else {}
    skipped = str(build_outputs.get("skip", "")).lower() == "true"
    report = None
    if args.report and Path(args.report).exists():
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    health_path = Path(args.archive) / HEALTH
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
    index = read_index(Path(args.archive))
    decision = decide(jobs=jobs, report=report, health=health, archive_dates=[e["date"] for e in index],
                      today=datetime.now(SGT).date(), scheduled=_flag(args.scheduled),
                      use_model=_flag(args.use_model), no_model=_flag(args.no_model),
                      break_feed=args.break_feed, archived=_flag(args.archived), skipped=skipped,
                      archive_readable=_flag(args.archive_readable), run_url=args.run_url)
    print(json.dumps(decision, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
