from __future__ import annotations

import datetime as dt
import re

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
_LONG = re.compile(r"\b(" + "|".join(MONTHS) + r") (\d{1,2}), (\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def long_form(d: dt.date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def parse(value) -> dt.date | None:
    """ISO or 'Month D, YYYY'. Anything else is unreadable, and unreadable means missing."""
    if isinstance(value, dt.date):
        return value
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        m = _LONG.fullmatch(value.strip())
        return dt.date(int(m[3]), MONTHS.index(m[1]) + 1, int(m[2])) if m else None


def dates_in(text: str) -> list[dt.date]:
    out = [dt.date(int(m[3]), MONTHS.index(m[1]) + 1, int(m[2])) for m in _LONG.finditer(text)]
    out += [dt.date(int(m[1]), int(m[2]), int(m[3])) for m in _ISO.finditer(text)]
    return out
