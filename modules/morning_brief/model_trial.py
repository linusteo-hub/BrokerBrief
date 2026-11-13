"""
Compare writer models on the fixture payload, to choose the cheapest one that
passes the gate. Needs ANTHROPIC_API_KEY; spends real (small) amounts.

    python -m modules.morning_brief.model_trial --runs 3
    python -m modules.morning_brief.model_trial --models claude-haiku-5-5 claude-sonnet-5-5 --runs 5

For each model and run it builds the brief from tests/fixtures/payload/
from_fixtures.json and records: summaries accepted on the first try, accepted
after the retry, withheld (with the reasons), whether the brief passed the
whole-brief gate, tokens and cost. A model "passes" if every run publishes
and nothing is withheld.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from modules.morning_brief.writer import PRICES, BriefRefused, build_brief, make_client

FIXTURE = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "payload" / "from_fixtures.json"


def trial(client, model: str, runs: int, payload: dict) -> dict:
    result = {"model": model, "runs": runs, "published": 0, "first_try": 0, "after_retry": 0,
              "withheld": 0, "withheld_reasons": Counter(), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for _ in range(runs):
        try:
            _, report = build_brief(payload, client, model)
        except BriefRefused as refused:
            result["withheld_reasons"]["REFUSED: " + refused.problems[0].code] += 1
            continue
        writer = report["writer"]
        result["published"] += 1
        attempts = writer["attempts"]
        if attempts and "error" not in attempts[0]:
            resent = attempts[1].get("items_sent", 0) if len(attempts) > 1 else 0
            first_ok = attempts[0]["items_sent"] - resent
            result["first_try"] += first_ok
            result["after_retry"] += len(writer["written"]) - first_ok
        result["withheld"] += len(writer["withheld"])
        for problems in writer["withheld"].values():
            for p in problems:
                result["withheld_reasons"][p["code"]] += 1
        for a in attempts:
            result["input_tokens"] += a.get("input_tokens") or 0
            result["output_tokens"] += a.get("output_tokens") or 0
            result["cost_usd"] += a.get("cost_usd") or 0
    result["passes"] = result["published"] == runs and result["withheld"] == 0
    result["cost_per_brief_usd"] = result["cost_usd"] / runs if runs else 0
    result["withheld_reasons"] = dict(result["withheld_reasons"])
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.model_trial",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", nargs="+", default=["claude-haiku-5-5", "claude-sonnet-5-5"],
                        choices=sorted(PRICES))
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    client = make_client(os.environ.get("ANTHROPIC_API_KEY"))
    if client is None:
        print("ANTHROPIC_API_KEY is not set; nothing to measure.", file=sys.stderr)
        return 2
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = [trial(client, model, args.runs, payload) for model in args.models]
    print(json.dumps(results, indent=2))
    cheapest = next((r["model"] for r in sorted(results, key=lambda r: PRICES[r["model"]][1]) if r["passes"]), None)
    print(f"\nCheapest model that passed every run: {cheapest or 'none'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
