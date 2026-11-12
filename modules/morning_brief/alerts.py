"""
modules/morning_brief/alerts.py

Decides whether a run needs Linus's attention. The workflow acts on the
decision with the GitHub CLI: one open issue labelled `brief-alert` at a
time, a comment on it for each further problem day, and closed with a
comment by the next clean run.

    python -m modules.morning_brief.alerts --archive <dir> --outcome success \\
        --report out/validation.json --run-url <url> [--failed-step <name>] \\
        [--expect-model] > decision.json

Alert when:
- the run failed at any step (a crash, a network error in our own code);
- the gate refused the brief (code-level problem: nothing was published);
- the writer could not reach the model although a key is configured
  (expired or revoked key, no credit, outage), so news went out as headlines;
- a section has been empty for EMPTY_DAYS_ALERT consecutive run dates
  (one or two empty days are normal: a feed has a bad morning).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from modules.morning_brief.archive import HEALTH

EMPTY_DAYS_ALERT = 3
LABEL = "brief-alert"
TITLE = "Morning brief needs attention"


def decide(*, outcome: str, report: Optional[dict], health: Optional[dict], expect_model: bool,
           failed_step: str = "", run_url: str = "") -> dict:
    reasons = []
    if outcome != "success":
        reasons.append(f"The run failed{' at step: ' + failed_step if failed_step else ''}. No brief was archived "
                       "or published from this run.")
    if report is not None and not report.get("published"):
        codes = sorted({p["code"] for p in report.get("refused_because", [])})
        reasons.append("The publishing gate refused the brief, so nothing was published. Problem codes: "
                       + (", ".join(codes) or "none recorded") + ". This points to a bug in BrokerBrief's code.")
    writer = (report or {}).get("writer") or {}
    if expect_model and writer.get("status") in ("model_unavailable", "no_model"):
        reasons.append(f"The writer could not use the model: {writer.get('detail') or writer.get('status')}. "
                       "News went out as headline and link only. Check the API key and credit "
                       "(docs/operations.md, 'Rotate the API key').")
    for section, days in sorted(((health or {}).get("empty_streak_days") or {}).items()):
        if days >= EMPTY_DAYS_ALERT:
            reasons.append(f"Section `{section}` has been empty for {days} days running. "
                           "Its reason is in the latest brief and in validation.json.")
    action = "alert" if reasons else "clear"
    lines = [f"- {r}" for r in reasons]
    if run_url:
        lines.append(f"\nRun: {run_url}")
    if report is not None and report.get("brief_date"):
        lines.insert(0, f"Brief date: {report['brief_date']}\n")
    return {"action": action, "label": LABEL, "title": TITLE, "reasons": reasons, "body": "\n".join(lines)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.alerts")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--outcome", required=True)
    parser.add_argument("--report")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--failed-step", default="")
    parser.add_argument("--expect-model", action="store_true")
    args = parser.parse_args(argv)
    report = None
    if args.report and Path(args.report).exists():
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    health_path = Path(args.archive) / HEALTH
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else None
    if report is None and args.outcome == "success":
        args.outcome, args.failed_step = "failure", args.failed_step or "no validation report was produced"
    print(json.dumps(decide(outcome=args.outcome, report=report, health=health, expect_model=args.expect_model,
                            failed_step=args.failed_step, run_url=args.run_url), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
