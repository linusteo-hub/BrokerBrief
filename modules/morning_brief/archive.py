"""
modules/morning_brief/archive.py

The public archive: one folder per brief date on the `briefs` branch,

    briefs/YYYY/MM/DD/brief.md          (only if the brief was published)
    briefs/YYYY/MM/DD/payload.json
    briefs/YYYY/MM/DD/validation.json
    briefs/index.json                   one line per run date, newest first
    briefs/health.json                  consecutive days each section has been empty

Retention (Decision D7): everything is kept for 12 months, then reviewed.
Size: about 50 KB a day before git compression, about 19 MB a year.

Re-running a date (the fallback schedule, or a manual re-run) replaces that
date's folder and its index entry; it never adds a duplicate.
"""

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

INDEX = "briefs/index.json"
HEALTH = "briefs/health.json"
EMPTY_STATUSES = ("missing",)          # not_covered is a standing decision, not a failure


def day_dir(root: Path, brief_date: str) -> Path:
    d = date.fromisoformat(brief_date)
    return Path(root) / "briefs" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"


def has_brief(root: Path, brief_date: str) -> bool:
    return (day_dir(root, brief_date) / "brief.md").exists()


def read_index(root: Path) -> list:
    path = Path(root) / INDEX
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def latest_payload(root: Path, before: str) -> Optional[Path]:
    """The payload of the most recent *published* brief dated before `before`."""
    for entry in read_index(root):
        if entry["date"] < before and entry["published"]:
            path = day_dir(root, entry["date"]) / "payload.json"
            if path.exists():
                return path
    return None


def store(root: Path, out_dir: Path, run_info: Optional[dict] = None) -> dict:
    """Copy a run's outputs into the archive and update the index and health
    files. Returns the index entry. `run_info` carries what the workflow knows
    that the files do not (run URL, failed step)."""
    out_dir = Path(out_dir)
    report = json.loads((out_dir / "validation.json").read_text(encoding="utf-8"))
    brief_date = report["brief_date"]
    target = day_dir(root, brief_date)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in ("brief.md", "payload.json", "validation.json"):
        if (out_dir / name).exists():
            shutil.copy2(out_dir / name, target / name)

    writer = report.get("writer") or {}
    entry = {
        "date": brief_date,
        "published": bool(report.get("published")),
        "writer_status": writer.get("status"),
        "withheld": len(writer.get("withheld") or {}),
        "cost_usd": writer.get("total_cost_usd"),
        "refused": [p["code"] for p in report.get("refused_because", [])],
        "sections": report.get("section_status", {}),
        **(run_info or {}),
    }
    index = [e for e in read_index(root) if e["date"] != brief_date] + [entry]
    index.sort(key=lambda e: e["date"], reverse=True)
    write_json(Path(root) / INDEX, index)
    write_json(Path(root) / HEALTH, health(index))
    return entry


def health(index: list) -> dict:
    """For each section, how many consecutive run dates (newest first) it has
    been empty for. Dates with no run at all break nothing here: a missing
    day is caught by the staleness alert instead."""
    streaks: dict = {}
    sections = {k for e in index for k in e.get("sections", {})}
    for section in sorted(sections):
        n = 0
        for entry in index:
            if entry.get("sections", {}).get(section) in EMPTY_STATUSES:
                n += 1
            else:
                break
        streaks[section] = n
    return {"latest_date": index[0]["date"] if index else None,
            "latest_published": index[0]["published"] if index else None,
            "empty_streak_days": streaks}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
