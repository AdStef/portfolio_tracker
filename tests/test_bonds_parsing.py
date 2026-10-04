from datetime import date

import pytest

from app.parsing import parse_date, parse_number
from app.services import bonds


@pytest.mark.parametrize("raw,expected", [
    ("1 000,00 zł", 1000.0), ("229.00", 229.0), ("11,232996", 11.232996), ("1.234,5", 1234.5),
    ("1,234.5", 1234.5), ("-1 000 zł", -1000.0), ("", None), ("− 5", -5.0),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_parse_date():
    assert parse_date("Feb 19, 2026") == "2026-02-19"
    assert parse_date("10.01.2024") == "2024-01-10"


def test_symbol_parsing():
    p = bonds.parse_symbol("EDO-100134")
    assert p == {"series": "EDO", "maturity": date(2034, 1, 10), "purchase_date": date(2024, 1, 10)}
    assert bonds.parse_symbol("WSE:XTB") == {}


def test_edo_capitalizes_and_indexes_with_cpi_two_months_back():
    params = bonds.load_params("EDO-100134", {"first_rate": 6.8, "margin": 1.25})
    cpi = {"2024-11": 4.7}  # period 2 starts 2025-01 -> uses Nov 2024 CPI
    v = bonds.value_on(params, date(2025, 7, 10), cpi)
    rate2 = 4.7 + 1.25
    base = 106.8
    assert v.period == 2 and v.rate == pytest.approx(rate2)
    assert v.value == pytest.approx(round(base + round(base * rate2 / 100 * 181 / 365, 2), 2))
    assert v.fee == 2.0


def test_coi_pays_out_interest_and_negative_cpi_floors_at_margin():
    params = bonds.load_params("COI-100128", {"first_rate": 6.5, "margin": 1.25})
    v = bonds.value_on(params, date(2025, 1, 10), {"2024-11": -1.0})
    assert v.value == 100.0 and v.rate == pytest.approx(1.25)
    mid = bonds.value_on(params, date(2024, 7, 10), {})
    assert mid.value == pytest.approx(100 + round(6.5 * 182 / 366, 2))
    assert mid.fee == 0.7


def test_missing_rate_values_at_nominal():
    params = bonds.load_params("TOS-300927", {})
    assert bonds.value_on(params, date(2025, 1, 1), {}).warnings == ["bond_params_missing"]
