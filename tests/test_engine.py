from datetime import date

import pytest

from app.services import engine
from app.services.engine import Account, Instrument, Person, Txn

P = [Person(1, "Adam")]
EURPLN = Instrument(100, "EURPLN", "EUR/PLN", "FX", "PLN")
STOCK = Instrument(1, "WSE:XTB", "XTB", "STOCK_PL", "PLN")
ETF = Instrument(2, "AMS:IWDA", "IWDA", "ETF_EQUITY", "EUR")


def run(accounts, txns, prices=None, instruments=(STOCK, ETF, EURPLN), as_of=date(2024, 1, 31)):
    return engine.run(P, accounts, list(instruments), txns, prices or {}, {}, as_of)["dashboard"]


def test_fifo_realized_and_belka_on_regular_account():
    acc = Account(1, 1, "XTB", "REGULAR")
    txns = [
        Txn(1, 1, "2024-01-02", "DEPOSIT", 1000, "PLN"),
        Txn(2, 1, "2024-01-03", "BUY", -100, "PLN", 1, 10, 10),
        Txn(3, 1, "2024-01-04", "BUY", -200, "PLN", 1, 10, 20),
        Txn(4, 1, "2024-01-05", "SELL", 150, "PLN", 1, 10, 15),  # sells the first lot: +50 realized
    ]
    d = run([acc], txns, {1: [("2024-01-30", 30.0)]})
    t = d["by_account"]["1"]["totals"]
    assert t["realized"] == pytest.approx(50)
    assert t["positions_value"] == pytest.approx(300)
    assert t["gross"] == pytest.approx(300 + 850)
    assert t["unrealized"] == pytest.approx(100)
    assert t["net"] == pytest.approx(1150 - 19)
    assert t["profit"] == pytest.approx(150)


def test_eur_cash_fx_exchange_and_cost_in_pln():
    acc = Account(1, 1, "XTB EUR", "REGULAR", "EUR")
    txns = [
        Txn(1, 1, "2024-01-02", "DEPOSIT", 430, "PLN"),
        Txn(2, 1, "2024-01-02", "FX_EXCHANGE", -430, "PLN", counter_amount=100, counter_currency="EUR"),
        Txn(3, 1, "2024-01-03", "BUY", -80, "EUR", 2, 1, 80, amount_pln=344),
    ]
    prices = {2: [("2024-01-30", 90.0)], 100: [("2024-01-01", 4.3), ("2024-01-30", 4.0)]}
    d = run([acc], txns, prices)
    a = d["by_account"]["1"]
    assert a["cash"] == {"EUR": 20}
    pos = a["positions"][0]
    assert pos["cost"] == pytest.approx(344)
    assert pos["value"] == pytest.approx(360)
    assert a["totals"]["gross"] == pytest.approx(360 + 80)
    assert d["fx"]["EUR"] == 4.0


def test_retirement_rules():
    accounts = [Account(1, 1, "IKE", "IKE"), Account(2, 1, "IKZE", "IKZE"), Account(3, 1, "PPK", "PPK")]
    txns = [
        Txn(1, 1, "2024-01-02", "DEPOSIT", 1000, "PLN"),
        Txn(2, 1, "2024-01-02", "BUY", -1000, "PLN", 1, 100, 10),
        Txn(3, 2, "2024-01-02", "DEPOSIT", 1000, "PLN"),
        Txn(4, 3, "2024-01-02", "DEPOSIT", 100, "PLN"),
        Txn(5, 3, "2024-01-02", "EMPLOYER_CONTRIBUTION", 100, "PLN"),
        Txn(6, 3, "2024-01-02", "STATE_CONTRIBUTION", 250, "PLN"),
    ]
    d = run(accounts, txns, {1: [("2024-01-30", 12.0)]})
    ike, ikze, ppk = (d["by_account"][str(i)]["totals"] for i in (1, 2, 3))
    assert ike["net"] == pytest.approx(1200 - 0.19 * 200)
    assert ikze["net"] == pytest.approx(900)
    assert ppk["net"] == pytest.approx(450 - 30)
    assert d["totals"]["retirement_gross"] == pytest.approx(1200 + 1000 + 450)


def test_bond_formula_valuation_and_fee():
    acc = Account(1, 1, "Obligacje", "BONDS")
    bond = Instrument(5, "TOS-020127", "TOS", "BOND_GOV_PL", "PLN", "bond_formula", '{"first_rate": 6.0}')
    txns = [
        Txn(1, 1, "2024-01-02", "DEPOSIT", 1000, "PLN"),
        Txn(2, 1, "2024-01-02", "BUY", -1000, "PLN", 5, 10, 100),
    ]
    d = run([acc], txns, instruments=[bond], as_of=date(2025, 1, 2))
    pos = d["by_account"]["1"]["positions"][0]
    assert pos["price"] == pytest.approx(106.0)
    assert pos["liquidation_fee"] == pytest.approx(7.0)
    # gain after fee = 60 - 7 = 53 -> Belka 10.07
    assert d["totals"]["net"] == pytest.approx(1060 - 7 - 0.19 * 53)


def test_xirr_simple_year():
    acc = Account(1, 1, "A", "REGULAR")
    txns = [Txn(1, 1, "2023-01-01", "DEPOSIT", 1000, "PLN"), Txn(2, 1, "2023-01-01", "BUY", -1000, "PLN", 1, 100, 10)]
    d = run([acc], txns, {1: [("2023-12-31", 11.0), ("2024-01-01", 11.0)]}, as_of=date(2024, 1, 1))
    assert d["totals"]["xirr"] == pytest.approx(0.10, abs=1e-3)
