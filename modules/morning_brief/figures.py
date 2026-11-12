"""
modules/morning_brief/figures.py

Builds the payload's numeric items. All arithmetic, rounding and formatting
happens here, so the writer model only ever copies display strings.

A figure looks like:
    {
      "id": "brent_spot", "label": "...", "unit": "USD/bbl",
      "value": 84.2, "display": "USD 84.20/bbl",
      "as_of": "2026-10-06", "as_of_display": "6 October 2026",
      "changes": [ {"basis": "...", "compared_with": "...",
                    "abs_display": "USD 0.71/bbl", "pct_display": "0.84%",
                    "direction": "down", ...} ],
      "source_id": "eia_spot", "quality_tier": "LIVE_API",
    }

Direction is taken from the change *as displayed*: if the absolute change
rounds to zero at display precision it is "flat", otherwise its sign. That way
the text can never say "rose USD 0.00" or "flat" next to a visible move.
"""

from datetime import date
from typing import Callable, Optional

Formatter = Callable[[float], str]


def fmt_date(d: date) -> str:
    """Day-month-year in words, e.g. '6 October 2026'."""
    return f"{d.day} {d.strftime('%B %Y')}"


def money(unit: str, decimals: int) -> Formatter:
    """Formatter for 'USD 84.20/bbl'-style strings. `unit` is e.g. 'USD/bbl'."""
    currency, _, per = unit.partition("/")
    suffix = f"/{per}" if per else ""
    return lambda v: f"{currency} {v:,.{decimals}f}{suffix}"


def count(noun: str) -> Formatter:
    """Formatter for counts, e.g. '312 transits', '1 transit'. `noun` is plural."""
    singular = noun[:-1] if noun.endswith("s") else noun
    return lambda v: f"{v:,.0f} {singular if round(v) == 1 else noun}"


def make_change(current: float, previous: float, fmt: Formatter, *, decimals: int,
                basis: str, compared_with: str) -> dict:
    """Pre-computed change from `previous` to `current`, with display strings."""
    abs_change = round(current - previous, decimals)
    if abs_change == 0:
        direction = "flat"
    else:
        direction = "up" if abs_change > 0 else "down"
    pct = None if previous == 0 else round((current - previous) / previous * 100, 2)
    return {
        "basis": basis,
        "compared_with": compared_with,
        "previous_value": previous,
        "previous_display": fmt(previous),
        "abs_change": abs_change,
        "abs_display": fmt(abs(abs_change)),
        "pct_change": pct,
        "pct_display": None if pct is None else f"{abs(pct):.2f}%",
        "direction": direction,
    }


def make_figure(*, figure_id: str, label: str, unit: str, value: float, fmt: Formatter,
                as_of: date, source_id: str, quality_tier: str,
                changes: Optional[list] = None, notes: str = "") -> dict:
    return {
        "id": figure_id,
        "label": label,
        "unit": unit,
        "value": value,
        "display": fmt(value),
        "as_of": as_of.isoformat(),
        "as_of_display": fmt_date(as_of),
        "changes": changes or [],
        "source_id": source_id,
        "quality_tier": quality_tier,
        "notes": notes,
    }
