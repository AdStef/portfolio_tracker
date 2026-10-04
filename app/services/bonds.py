"""Valuation of Polish retail treasury bonds (obligacje skarbowe) from their series rules.

Each purchase date is its own instrument (legacy symbol format ``EDO-100134`` = EDO maturing 10.01.2034),
because interest periods run from the purchase day. Parameters live in ``instrument.source_config``:

    {
      "series": "EDO",              # optional, derived from the symbol
      "purchase_date": "2024-01-10",# optional, derived from the symbol
      "first_rate": 6.8,            # % in the first period (required)
      "margin": 1.25,               # % added to CPI from period 2 on (indexed series)
      "fee": 2.0,                   # early-redemption fee per bond (optional, series default)
      "period_rates": {"2": 5.9}    # optional manual override per period number (1-based)
    }

Prices are returned per bond (nominal 100 PLN).
"""

from __future__ import annotations

import calendar
import json
import re
from dataclasses import dataclass
from datetime import date

NOMINAL = 100.0


@dataclass(frozen=True)
class SeriesRule:
    term_months: int
    period_months: int
    capitalized: bool  # interest added to the base each period (EDO) vs paid out (COI)
    indexed: bool  # period 2+ rate = CPI + margin
    fee: float  # default early-redemption fee per bond


SERIES = {
    "OTS": SeriesRule(3, 3, False, False, 0.0),
    "TOS": SeriesRule(36, 12, True, False, 0.70),
    "COI": SeriesRule(48, 12, False, True, 0.70),
    "EDO": SeriesRule(120, 12, True, True, 2.00),
    "ROS": SeriesRule(72, 12, True, True, 0.70),
    "ROD": SeriesRule(144, 12, True, True, 2.00),
    # Floating (NBP reference rate) series: enter each month's rate in period_rates.
    "ROR": SeriesRule(12, 1, False, False, 0.50),
    "DOR": SeriesRule(24, 1, False, False, 0.70),
}

SYMBOL_RE = re.compile(r"^(?P<series>[A-Z]{3})-(?P<d>\d{2})(?P<m>\d{2})(?P<y>\d{2})$")


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def parse_symbol(symbol: str) -> dict:
    """``EDO-100134`` -> {"series": "EDO", "maturity": date(2034, 1, 10), "purchase_date": date(2024, 1, 10)}."""
    m = SYMBOL_RE.match(symbol or "")
    if not m or m["series"] not in SERIES:
        return {}
    maturity = date(2000 + int(m["y"]), int(m["m"]), int(m["d"]))
    rule = SERIES[m["series"]]
    return {
        "series": m["series"],
        "maturity": maturity,
        "purchase_date": add_months(maturity, -rule.term_months),
    }


@dataclass
class BondParams:
    series: str
    purchase_date: date
    first_rate: float | None
    margin: float
    fee: float
    period_rates: dict[int, float]

    @property
    def rule(self) -> SeriesRule:
        return SERIES[self.series]

    @property
    def maturity(self) -> date:
        return add_months(self.purchase_date, self.rule.term_months)


def load_params(symbol: str, source_config: str | dict | None) -> BondParams | None:
    cfg = source_config if isinstance(source_config, dict) else json.loads(source_config or "{}")
    derived = parse_symbol(symbol)
    series = (cfg.get("series") or derived.get("series") or "").upper()
    if series not in SERIES:
        return None
    purchase = cfg.get("purchase_date") or derived.get("purchase_date")
    if purchase is None:
        return None
    if isinstance(purchase, str):
        purchase = date.fromisoformat(purchase)
    return BondParams(
        series=series,
        purchase_date=purchase,
        first_rate=_float_or_none(cfg.get("first_rate")),
        margin=float(cfg.get("margin") or 0.0),
        fee=float(cfg["fee"]) if cfg.get("fee") not in (None, "") else SERIES[series].fee,
        period_rates={int(k): float(v) for k, v in (cfg.get("period_rates") or {}).items()},
    )


def _float_or_none(v):
    return None if v in (None, "") else float(v)


@dataclass
class BondValue:
    value: float  # gross value per bond (nominal + accrued, capitalized interest included)
    accrued: float  # interest that early redemption would pay out (basis for fee cap)
    fee: float  # early-redemption fee per bond, capped at accrued interest
    period: int  # 1-based current interest period
    rate: float | None  # % in current period
    warnings: list[str]


def value_on(params: BondParams, on: date, cpi: dict[str, float]) -> BondValue:
    """Value of one bond on ``on``. ``cpi`` maps 'YYYY-MM' -> y/y CPI in %."""
    rule = params.rule
    warnings: list[str] = []
    if params.first_rate is None:
        return BondValue(NOMINAL, 0.0, 0.0, 1, None, ["bond_params_missing"])

    on = min(on, params.maturity)
    if on <= params.purchase_date:
        return BondValue(NOMINAL, 0.0, 0.0, 1, params.first_rate, warnings)

    base = NOMINAL
    k = 0
    while True:
        start = add_months(params.purchase_date, k * rule.period_months)
        end = add_months(params.purchase_date, (k + 1) * rule.period_months)
        rate = _period_rate(params, k + 1, start, cpi, warnings)
        if on < end or end >= params.maturity:
            elapsed = (on - start).days
            accrued_now = round(base * rate / 100 * elapsed / (end - start).days, 2)
            value = round(base + accrued_now, 2)
            accrued = value - NOMINAL if rule.capitalized else accrued_now
            fee = min(params.fee, max(accrued, 0.0)) if on < params.maturity else 0.0
            return BondValue(value, round(accrued, 2), round(fee, 2), k + 1, rate, warnings)
        if rule.capitalized:
            base = round(base * (1 + rate / 100), 2)
        k += 1


def _period_rate(params: BondParams, n: int, start: date, cpi: dict[str, float], warnings: list[str]) -> float:
    if n in params.period_rates:
        return params.period_rates[n]
    if n == 1 or not params.rule.indexed:
        return params.first_rate
    # Rate for period n uses y/y CPI for the month two months before the period starts.
    ref = add_months(start.replace(day=1), -2).strftime("%Y-%m")
    if ref in cpi:
        inflation = cpi[ref]
    else:
        earlier = [m for m in cpi if m <= ref]
        if not earlier:
            warnings.append("cpi_missing")
            return params.first_rate
        warnings.append("cpi_missing")
        inflation = cpi[max(earlier)]
    return max(inflation, 0.0) + params.margin
