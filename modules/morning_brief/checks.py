"""
modules/morning_brief/checks.py

Validation of fetched values, before they enter the payload. Each check
returns None when the value passes, or a plain-English reason when it fails.
A value that fails any check is excluded and the reason recorded; it is never
"corrected".
"""

from datetime import date, timedelta
from typing import Optional

from modules.morning_brief.figures import fmt_date


def check_range(value: float, low: float, high: float, display: str) -> Optional[str]:
    if not (low <= value <= high):
        return f"{display} is outside the plausible range {low:g}–{high:g}, so it was not used"
    return None


def check_staleness(as_of: date, today: date, max_age: timedelta) -> Optional[str]:
    age = today - as_of
    if age > max_age:
        return (f"latest value is dated {fmt_date(as_of)}, {age.days} days old "
                f"(limit {max_age.days} days)")
    if age < timedelta(0):
        return f"latest value is dated {fmt_date(as_of)}, which is in the future"
    return None
