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
- the writer could not use the model on a run that should have used it
  (scheduled runs always should: a deleted or mistyped secret is a failure);
- a section has been empty on EMPTY_DAYS_ALERT consecutive run dates;
- no brief has been archived for MISSED_DAYS_ALERT days or more;
- a failure test: the broken source is reported, to prove the alert path.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from modules.morning_brief.archive import HEALTH, read_index

EMPTY_DAYS_ALERT = 3
MISSED_DAYS_ALERT = 2
LABEL, TEST_LABEL = "brief-alert", "brief-alert-test"
TITLE = "Morning brief needs attention"
SGT = timezone(timedelta(hours=8))
JOB_NAMES = {"keepalive": "Keep the schedules alive", "build": "Build and write the brief",
             "archive": "Archive to the briefs branch", "site": "Publish to GitHub Pages"}


def decide(*, jobs: dict, report: Optional[dict], health: Optional[dict], latest_archived: Optional[str],
           today: date, scheduled: bool, has_model_key: bool, no_model: bool, break_feed: str = "none",
           archived: bool = False, run_url: str = "") -> dict:
    reasons = []
    for job, result in jobs.items():
        if result in ("failure", "cancelled"):
            reasons.append(f"Job \"{JOB_NAMES.get(job, job)}\" {'was cancelled or timed out' if result == 'cancelled' else 'failed'}. "
                           "Open the run to see the step.")
    build_ran = jobs.get("build") == "success"
    if build_ran and report is None:
        reasons.append("The build finished but left no validation report.")
    if report is not None and report.get("crashed"):
        reasons.append(f"The writer crashed, so nothing was published: {report['crashed']}")
    elif report is not None and not report.get("published"):
        codes = sorted({p["code"] for p in report.get("refused_because", [])})
        reasons.append("The publishing gate refused the brief, so nothing was published. Problem codes: "
                       + (", ".join(codes) or "none recorded") + ". This points to a bug in BrokerBrief's code.")
    writer = (report or {}).get("writer") or {}
    model_expected = scheduled or (has_model_key and not no_model)
    if model_expected and writer.get("status") in ("model_unavailable", "no_model"):
        reasons.append(f"The writer could not use the model: {writer.get('detail') or writer.get('status')}. "
                       "News went out as headline and link only. Check the ANTHROPIC_API_KEY secret, the key, "
                       "and credit (docs/operations.md, \"Rotate the API key\").")
    if archived:
        for section, days in sorted(((health or {}).get("empty_streak_days") or {}).items()):
            if days >= EMPTY_DAYS_ALERT:
                reasons.append(f"Section `{section}` has been empty on {days} run dates in a row. "
                               "Its reason is in the latest brief and in validation.json.")
    if scheduled and jobs.get("build") == "success":
        if latest_archived is None or (today - date.fromisoformat(latest_archived)).days >= MISSED_DAYS_ALERT:
            reasons.append(f"No brief has been archived since {latest_archived or 'the archive began'}.")
    if break_feed and break_feed != "none":
        reasons.append(f"Failure test: `{break_feed}` was broken on purpose. Check that the brief marks its "
                       "data as missing with the reason, and that this issue appeared. This run was not archived "
                       "or published.")

    lines = [f"- {r}" for r in reasons]
    if report is not None and report.get("brief_date"):
        lines.insert(0, f"Brief date: {report['brief_date']}\n")
    if run_url:
        lines.append(f"\nRun: {run_url}")
    test = not scheduled
    return {"action": "alert" if reasons else "clear", "label": TEST_LABEL if test else LABEL,
            "title": TITLE + (" (manual run)" if test else ""), "reasons": reasons, "body": "\n".join(lines)}


def _flag(value: str) -> bool:
    return str(value).strip().lower() == "true"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.alerts")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--report")
    parser.add_argument("--jobs-json", default="{}", help="the workflow's toJSON(needs)")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--scheduled", default="false")
    parser.add_argument("--has-model-key", default="false")
    parser.add_argument("--no-model", default="false")
    parser.add_argument("--break-feed", default="none")
    parser.add_argument("--archived", default="false")
    args = parser.parse_args(argv)

    needs = json.loads(args.jobs_json or "{}")
    jobs = {name: info.get("result") if isinstance(info, dict) else info for name, info in needs.items()}
    report = None
    if args.report and Path(args.report).exists():
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    health_path = Path(args.archive) / HEALTH
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
    index = read_index(Path(args.archive))
    latest = next((e["date"] for e in index if e.get("published")), None)
    decision = decide(jobs=jobs, report=report, health=health, latest_archived=latest,
                      today=datetime.now(SGT).date(), scheduled=_flag(args.scheduled),
                      has_model_key=_flag(args.has_model_key), no_model=_flag(args.no_model),
                      break_feed=args.break_feed, archived=_flag(args.archived), run_url=args.run_url)
    print(json.dumps(decision, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
