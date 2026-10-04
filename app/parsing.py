"""Lenient parsing of numbers and dates coming from CSV files and forms (Polish and English formats)."""

import re
from datetime import date, datetime

_CURRENCY_JUNK = re.compile(r"(zł|zl|pln|eur|usd|€|\$|\s| | )", re.IGNORECASE)


def parse_number(value) -> float | None:
    """'1 000,50 zł' -> 1000.5, '229.00' -> 229.0, '1.234,5' -> 1234.5, '' -> None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = _CURRENCY_JUNK.sub("", str(value)).replace("−", "-")
    if s in ("", "-"):
        return None
    if "," in s and "." in s:
        # whichever separator comes last is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError as exc:
        raise ValueError(f"not a number: {value!r}") from exc


_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y", "%b %d, %Y", "%Y-%m-%d %H:%M:%S",
                 "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M")


def parse_date(value) -> str:
    if isinstance(value, date):
        return value.isoformat()
    s = str(value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"not a date: {value!r}")
