"""
Run the morning-brief validator.

    python -m modules.morning_brief.validate --cases tests/fixtures/validator
    python -m modules.morning_brief.validate --payload payload.json --brief brief.md

--cases runs every *.json case in the folder. Each case says what it checks
and whether it must pass or fail. Several cases are built to fail (a number
not in the payload, a digit in a news summary, a wrong direction word, …):
the run succeeds only if every one of those is caught AND every good case
passes. Exit 0 if all cases behave as expected, 1 otherwise.

--payload/--brief checks one real brief. Exit 0 if it passes, 1 if not.

Case file format (JSON):
  {"description": "...",
   "check": "brief" | "text" | "summary" | "why",
   "payload": "<path under tests/fixtures>" or {inline payload},
   "payload_edits": [["sections.prices.items.0.value", 999]],   # optional
   "brief": "<path under tests/fixtures>",                       # check = brief
   "brief_replace": [["old text", "new text"]],                  # optional
   "text": "...",                                                # check = text / summary / why
   "item_id": "...",                                             # check = summary / why
   "expect": "pass" | "fail",
   "expect_codes": ["number_not_in_payload"]}                    # for fail cases
"""

import argparse
import copy
import json
import sys
from pathlib import Path

from modules.morning_brief.validator import (
    check_summary, check_text, check_why, news_items, validate_brief, validate_payload,
)

FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


def _load(ref, base: Path):
    return copy.deepcopy(ref) if isinstance(ref, dict) else json.loads((base / ref).read_text(encoding="utf-8"))


def _set(payload: dict, path: str, value) -> None:
    node = payload
    keys = [int(k) if k.isdigit() else k for k in path.split(".")]
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value


def run_case(case: dict, base: Path = FIXTURES) -> list:
    payload = _load(case["payload"], base)
    for path, value in case.get("payload_edits", []):
        _set(payload, path, value)
    check = case["check"]
    if check == "brief":
        brief = (base / case["brief"]).read_text(encoding="utf-8")
        for old, new in case.get("brief_replace", []):
            if old not in brief:
                raise ValueError(f"case edit does not apply: {old!r} not in the brief")
            brief = brief.replace(old, new)
        return validate_payload(payload) + validate_brief(brief, payload)
    if check == "text":
        return check_text(case["text"], payload)
    item = next(i for i in news_items(payload) if i["id"] == case["item_id"])
    item = {**item, "needs_why": item["section"] == "events"}
    return check_summary(case["text"], item) if check == "summary" else check_why(case["text"], item)


def run_cases(folder: Path) -> tuple:
    rows, ok = [], True
    for path in sorted(folder.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        problems = run_case(case)
        codes = sorted({p.code for p in problems})
        expected_fail = case["expect"] == "fail"
        if expected_fail:
            good = bool(problems) and set(case.get("expect_codes", [])) <= set(codes)
        else:
            good = not problems
        ok &= good
        rows.append((path.stem, case["expect"], "caught" if problems else "passed", codes, good, problems))
    return ok, rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief.validate",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", help="folder of validator case files")
    parser.add_argument("--payload")
    parser.add_argument("--brief")
    args = parser.parse_args(argv)

    if args.cases:
        ok, rows = run_cases(Path(args.cases))
        for name, expect, outcome, codes, good, problems in rows:
            mark = "OK  " if good else "FAIL"
            print(f"{mark} {name:<34} expect {expect:<4}  {outcome:<6}  {', '.join(codes) or '-'}")
            if not good:
                for p in problems[:5]:
                    print(f"       {p.code}: {p.message} [{p.where[:80]}]")
        caught = sum(1 for r in rows if r[1] == "fail" and r[4])
        print(f"\n{len(rows)} cases: {sum(r[4] for r in rows)} behaved as expected "
              f"({caught} of {sum(1 for r in rows if r[1] == 'fail')} must-fail cases caught).")
        return 0 if ok and rows else 1

    if args.payload and args.brief:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        brief = Path(args.brief).read_text(encoding="utf-8")
        problems = validate_payload(payload) + validate_brief(brief, payload)
        for p in problems:
            print(f"{p.code}: {p.message} [{p.where[:100]}]")
        print("PASS" if not problems else f"FAIL ({len(problems)} problems)")
        return 0 if not problems else 1

    parser.error("give --cases, or --payload and --brief")
    return 2


if __name__ == "__main__":
    sys.exit(main())
