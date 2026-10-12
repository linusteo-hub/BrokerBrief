"""
Build the morning-brief payload from live sources and print or save it.

    python -m modules.morning_brief                 # JSON to stdout
    python -m modules.morning_brief --out brief.json

Needs EIA_API_KEY in the environment (or in .env, if python-dotenv is
installed); without it the Prices section is marked missing. A summary goes
to stderr. Exit code 0 even when sections are missing (the brief still goes
out); non-zero if the allowlist or final gate refuses the payload.
"""

import argparse
import json
import os
import sys

from modules.morning_brief.allowlist import SourceNotAllowed
from modules.morning_brief.payload import fetch_and_build


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m modules.morning_brief", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", help="write the payload JSON here instead of stdout")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        payload = fetch_and_build(eia_api_key=os.environ.get("EIA_API_KEY"))
    except SourceNotAllowed as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)

    print(f"Morning brief payload for {payload['brief_date_display']}:", file=sys.stderr)
    def counts_text(counts):
        if not counts:
            return ""
        dropped = ", ".join(f"{k} {v}" for k, v in counts["dropped"].items() if v) or "none"
        wire = f"; {counts['wire_headline_only']} wire (headline only)" if counts.get("wire_headline_only") else ""
        return f"  [fetched {counts['fetched']}, kept {counts['kept']}; dropped: {dropped}{wire}]"

    for key, section in payload["sections"].items():
        line = f"  {key:<18} {section['status']}{counts_text(section['counts'])}"
        if section["reason"]:
            line += f" — {section['reason']}"
        print(line, file=sys.stderr)
        for sub_key, sub in section.get("subsections", {}).items():
            print(f"    {sub_key:<16} {sub['status']}{counts_text(sub['counts'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
