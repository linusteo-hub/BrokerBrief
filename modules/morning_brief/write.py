"""
Write and check the morning brief from a payload.

    python -m modules.morning_brief.write --payload payload.json --out-dir out/
    python -m modules.morning_brief.write --payload payload.json --out-dir out/ --previous yesterday.json
    python -m modules.morning_brief.write --payload payload.json --out-dir out/ --no-model

Reads ANTHROPIC_API_KEY from the environment (or .env if python-dotenv is
installed). Without a key, or with --no-model, news is published as headline
and link only and the report says so.

Writes, in --out-dir:
- validation.json  always: what was written, withheld or refused, and why;
- brief.md         only if the brief passed every code-level check;
- payload.json     the payload the brief was built from, without the news excerpts
                   (publishers' text, used only to brief the model).

Exit codes: 0 published (possibly with summaries withheld or news as
headline only); 3 refused by a code-level check, nothing published;
2 bad arguments or unreadable payload.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from modules.morning_brief.validator import problems_to_dicts
from modules.morning_brief.writer import (
    MODEL, BriefRefused, build_brief, make_client, public_payload, section_status,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.write",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--payload", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--previous", help="the previous brief's payload, to mark figures with no new data")
    parser.add_argument("--no-model", action="store_true", help="publish news as headline and link only")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    except (OSError, ValueError) as error:
        print(f"cannot read payload: {error}", file=sys.stderr)
        return 2

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # A brief.md left from an earlier run must never be mistaken for today's.
    for stale in ("brief.md", "validation.json", "payload.json"):
        (out / stale).unlink(missing_ok=True)
    client = None if args.no_model else make_client(os.environ.get("ANTHROPIC_API_KEY"))

    def save(report: dict) -> None:
        (out / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (out / "payload.json").write_text(json.dumps(public_payload(payload), indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")

    try:
        markdown, report = build_brief(payload, client, args.model, previous)
    except BriefRefused as refused:
        save({"brief_date": payload.get("brief_date"), "published": False,
              "refused_because": problems_to_dicts(refused.problems), "section_status": section_status(payload)})
        print(f"REFUSED: {refused}", file=sys.stderr)
        return 3
    except Exception as error:      # a crash still leaves a report for the alert step
        save({"brief_date": payload.get("brief_date"), "published": False,
              "crashed": f"{type(error).__name__}: {error}"[:300]})
        raise

    save(report)
    (out / "brief.md").write_text(markdown, encoding="utf-8")
    writer = report["writer"]
    print(f"Brief for {payload['brief_date_display']} written to {out / 'brief.md'}", file=sys.stderr)
    print(f"  writer: {writer['status']}{' — ' + writer['detail'] if writer['detail'] else ''}; "
          f"{len(writer['written'])} summaries written, {len(writer['withheld'])} withheld; "
          f"cost USD {writer['total_cost_usd']:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
