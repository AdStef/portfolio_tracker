"""Portfolio calculation engine.

Pure function of its inputs: replays every transaction day by day, values each account with the latest
known prices/FX, applies the exit-tax rules and produces the data that ends up in the JSON snapshots.
All money in the output is PLN; the browser converts to the display currency.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.constants import BASE_CURRENCY, RETIREMENT_KINDS
from app.services import bonds, tax
from app.services.metrics import xirr

STALE_AFTER_DAYS = 7
EPS = 1e-9


# ---------------------------------------------------------------- inputs


@dataclass
class Account:
    id: int
    person_id: int
    name: str
    kind: str
    currency: str = BASE_CURRENCY


@dataclass
class Person:
    id: int
    name: str


@dataclass
class Instrument:
    id: int
    symbol: str
    name: str | None
    asset_class: str
    currency: str
    price_source: str = "manual"
    source_config: str | None = None


@dataclass
class Txn:
    id: int
    account_id: int
    date: str
    type: str
    cash_amount: float
    cash_currency: str
    instrument_id: int | None = None
    quantity: float | None = None
    price: float | None = None
    fee: float = 0.0
    tax: float = 0.0
    amount_pln: float | None = None
    counter_amount: float | None = None
    counter_currency: str | None = None


# ---------------------------------------------------------------- market data


class Market:
    """Answers "what was the price / FX rate on day d" with carry-forward of the last known value."""

    def __init__(self, instruments: dict[int, Instrument], prices: dict[int, list[tuple[str, float]]],
                 txns: list[Txn], cpi: dict[str, float], warn):
        self.instruments = instruments
        self.cpi = cpi
        self.warn = warn
        self.fx_ids = {
            i.symbol[:3]: i.id
            for i in instruments.values()
            if i.asset_class == "FX" and len(i.symbol) == 6 and i.symbol.endswith(BASE_CURRENCY)
        }
        self.bond_params = {
            i.id: bonds.load_params(i.symbol, i.source_config)
            for i in instruments.values()
            if i.price_source == "bond_formula"
        }
        # Feed prices first; trade prices only fill days without a feed price (e.g. instruments with no source yet).
        series: dict[int, dict[str, tuple[float, str]]] = defaultdict(dict)
        for iid, rows in prices.items():
            for d, close in rows:
                series[iid][d] = (close, "feed")
        for t in txns:
            if t.type in ("BUY", "SELL") and t.instrument_id and (t.price or 0) > 0:
                series[t.instrument_id].setdefault(t.date, (t.price, "trade"))
        self._dates = {iid: sorted(s) for iid, s in series.items()}
        self._series = series

    def last_feed_date(self, iid: int, on: str) -> str | None:
        dates = self._dates.get(iid)
        if not dates:
            return None
        i = bisect.bisect_right(dates, on)
        return dates[i - 1] if i else None

    def price(self, iid: int, on: str) -> tuple[float, str | None, str]:
        """(price in instrument currency, price date, kind) where kind is feed|trade|bond|none."""
        inst = self.instruments[iid]
        if inst.price_source == "bond_formula":
            bv = self.bond(iid, on)
            return (bv.value if bv else bonds.NOMINAL), on, "bond"
        dates = self._dates.get(iid)
        if not dates:
            return 0.0, None, "none"
        i = bisect.bisect_right(dates, on)
        if i == 0:  # before the first known price: use the first one
            d = dates[0]
        else:
            d = dates[i - 1]
        close, kind = self._series[iid][d]
        return close, d, kind

    def bond(self, iid: int, on: str, report: bool = False) -> bonds.BondValue | None:
        """Bond value; ``report`` adds data-quality warnings (only for the as-of valuation, not history)."""
        params = self.bond_params.get(iid)
        inst = self.instruments[iid]
        if params is None:
            if report:
                self.warn("bond_params_missing", instrument=inst.symbol)
            return None
        bv = bonds.value_on(params, date.fromisoformat(on), self.cpi)
        if report:
            for w in bv.warnings:
                self.warn(w, instrument=inst.symbol)
        return bv

    def fx(self, currency: str, on: str) -> float:
        """PLN per 1 unit of currency."""
        if currency == BASE_CURRENCY:
            return 1.0
        iid = self.fx_ids.get(currency)
        if iid is None or not self._dates.get(iid):
            self.warn("fx_missing", currency=currency)
            return 0.0
        return self.price(iid, on)[0]


# ---------------------------------------------------------------- per-account state


@dataclass
class Lot:
    qty: float
    cost_pln: float  # incl. fees
    cost_native: float  # qty * price, instrument currency, excl. fees (for average price)


@dataclass
class AccountState:
    account: Account
    cash: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    lots: dict[int, list[Lot]] = field(default_factory=lambda: defaultdict(list))
    own_contrib: float = 0.0
    employer_contrib: float = 0.0
    state_contrib: float = 0.0
    realized: float = 0.0
    income: float = 0.0
    fees: float = 0.0
    taxes: float = 0.0
    flows: list[tuple[date, float]] = field(default_factory=list)  # investor view: money in < 0

    def qty(self, iid: int) -> float:
        return sum(l.qty for l in self.lots.get(iid, ()))

    # ---- transactions

    def apply(self, t: Txn, m: Market, warn) -> None:
        d = date.fromisoformat(t.date)
        fx_cash = m.fx(t.cash_currency, t.date)
        leg_pln = t.amount_pln if t.amount_pln is not None else abs(t.cash_amount) * fx_cash
        sign = 1.0 if t.cash_amount >= 0 else -1.0
        self.fees += (t.fee or 0.0) * fx_cash
        self.taxes += (t.tax or 0.0) * fx_cash
        self.cash[t.cash_currency] += t.cash_amount

        if t.type == "BUY":
            native = (t.quantity or 0) * (t.price or 0)
            cost = leg_pln if t.cash_amount else native * m.fx(m.instruments[t.instrument_id].currency, t.date)
            self.lots[t.instrument_id].append(Lot(t.quantity or 0.0, cost, native))
        elif t.type == "SELL":
            removed = self._remove(t.instrument_id, t.quantity or 0.0, warn, t)
            self.realized += leg_pln - removed
        elif t.type in ("DIVIDEND", "INTEREST"):
            self.income += sign * leg_pln
        elif t.type in ("FEE", "TAX"):
            if not t.fee and not t.tax:  # amount lives only in cash_amount
                if t.type == "FEE":
                    self.fees += leg_pln
                else:
                    self.taxes += leg_pln
        elif t.type in ("DEPOSIT", "WITHDRAWAL", "TRANSFER_IN", "TRANSFER_OUT"):
            moved = sign * leg_pln
            if t.instrument_id and t.quantity:  # in-kind security transfer
                inst = m.instruments[t.instrument_id]
                if t.type == "TRANSFER_IN":
                    cost = t.amount_pln if t.amount_pln is not None else (
                        t.quantity * (t.price or 0) * m.fx(inst.currency, t.date))
                    self.lots[t.instrument_id].append(Lot(t.quantity, cost, t.quantity * (t.price or 0)))
                    moved += cost
                else:
                    moved -= self._remove(t.instrument_id, t.quantity, warn, t)
            self.own_contrib += moved
            self.flows.append((d, -moved))
        elif t.type == "EMPLOYER_CONTRIBUTION":
            self.employer_contrib += sign * leg_pln
            self.flows.append((d, -sign * leg_pln))
        elif t.type == "STATE_CONTRIBUTION":
            self.state_contrib += sign * leg_pln
            self.flows.append((d, -sign * leg_pln))
        elif t.type == "FX_EXCHANGE":
            if t.counter_currency:
                self.cash[t.counter_currency] += t.counter_amount or 0.0

    def _remove(self, iid: int, qty: float, warn, t: Txn) -> float:
        """FIFO removal; returns PLN cost of removed units."""
        lots = self.lots.get(iid, [])
        cost = 0.0
        remaining = qty
        while remaining > EPS and lots:
            lot = lots[0]
            take = min(lot.qty, remaining)
            frac = take / lot.qty if lot.qty else 1.0
            cost += lot.cost_pln * frac
            lot.cost_pln -= lot.cost_pln * frac
            lot.cost_native -= lot.cost_native * frac
            lot.qty -= take
            remaining -= take
            if lot.qty <= 1e-6:
                lots.pop(0)
        if remaining > 1e-4:
            warn("oversold", account=self.account.name, txn=t.id, detail=round(remaining, 6))
        return cost

    # ---- valuation

    def value(self, on: str, m: Market, detailed: bool = False) -> dict:
        positions_value = liquidation = open_cost = 0.0
        positions = []
        for iid, lots in self.lots.items():
            qty = sum(l.qty for l in lots)
            if qty <= 1e-9:
                continue
            inst = m.instruments[iid]
            price, price_date, kind = m.price(iid, on)
            fx = m.fx(inst.currency, on)
            val = qty * price * fx
            cost = sum(l.cost_pln for l in lots)
            fee = 0.0
            bond_info = None
            if kind == "bond":
                bv = m.bond(iid, on, report=detailed)
                if bv:
                    fee = bv.fee * qty * fx
                    bond_info = {"accrued": bv.accrued, "fee": bv.fee, "period": bv.period, "rate": bv.rate}
            positions_value += val
            liquidation += fee
            open_cost += cost
            if detailed:
                cost_native = sum(l.cost_native for l in lots)
                positions.append({
                    "instrument_id": iid,
                    "symbol": inst.symbol,
                    "name": inst.name,
                    "asset_class": inst.asset_class,
                    "currency": inst.currency,
                    "quantity": qty,
                    "avg_price": cost_native / qty if qty else None,
                    "price": price,
                    "price_date": price_date,
                    "price_kind": kind,
                    "value": val,
                    "value_native": qty * price,
                    "cost": cost,
                    "unrealized": val - fee - cost,
                    "unrealized_pct": (val - fee - cost) / cost if cost > EPS else None,
                    "liquidation_fee": fee,
                    "bond": bond_info,
                })
        cash_value = 0.0
        cash = {}
        cash_pln = {}
        for ccy, amount in self.cash.items():
            if abs(amount) > 0.005:
                cash[ccy] = amount
                cash_pln[ccy] = amount * m.fx(ccy, on)
                cash_value += cash_pln[ccy]
        gross = positions_value + cash_value
        net, exit_tax = tax.net_value(
            self.account.kind, gross=gross, liquidation_fees=liquidation, positions_value=positions_value,
            open_cost=open_cost, own_contrib=self.own_contrib, employer_contrib=self.employer_contrib,
            state_contrib=self.state_contrib,
        )
        out = {
            "gross": gross,
            "net": net,
            "exit_tax": exit_tax,
            "positions_value": positions_value,
            "cash_value": cash_value,
            "open_cost": open_cost,
            "liquidation_fees": liquidation,
            "invested": self.own_contrib + self.employer_contrib + self.state_contrib,
        }
        if detailed:
            out["positions"] = positions
            out["cash"] = cash
            out["cash_pln"] = cash_pln
        return out


# ---------------------------------------------------------------- run

SUM_FIELDS = [
    "gross", "net", "exit_tax", "positions_value", "cash_value", "open_cost", "liquidation_fees", "invested",
    "own_contrib", "employer_contrib", "state_contrib", "realized", "income", "fees", "taxes",
    "retirement_gross", "retirement_net",
]


def run(persons: list[Person], accounts: list[Account], instruments: list[Instrument], txns: list[Txn],
        prices: dict[int, list[tuple[str, float]]], cpi: dict[str, float], as_of: date) -> dict:
    warnings: dict[tuple, dict] = {}

    def warn(code, **kw):
        key = (code,) + tuple(sorted((k, str(v)) for k, v in kw.items()))
        warnings.setdefault(key, {"code": code, **kw})

    inst_by_id = {i.id: i for i in instruments}
    as_of_s = as_of.isoformat()
    future = [t for t in txns if t.date > as_of_s]
    if future:
        warn("future_transactions", detail=len(future))
    txns = sorted((t for t in txns if t.date <= as_of_s), key=lambda t: (t.date, t.id))
    market = Market(inst_by_id, prices, txns, cpi, warn)
    states = {a.id: AccountState(a) for a in accounts}

    # ---- daily replay
    by_day: dict[str, list[Txn]] = defaultdict(list)
    for t in txns:
        by_day[t.date].append(t)
    start = date.fromisoformat(txns[0].date) if txns else as_of
    dates: list[str] = []
    hist = {a.id: {"gross": [], "net": [], "invested": []} for a in accounts}
    d = start
    while d <= as_of:
        ds = d.isoformat()
        for t in by_day.get(ds, ()):
            if t.account_id in states:
                states[t.account_id].apply(t, market, warn)
        dates.append(ds)
        for aid, st in states.items():
            v = st.value(ds, market)
            h = hist[aid]
            h["gross"].append(round(v["gross"], 2))
            h["net"].append(round(v["net"], 2))
            h["invested"].append(round(v["invested"], 2))
        d += timedelta(days=1)

    # ---- day change reference points: last two market days with a feed price for something held
    market_dates = set()
    for st in states.values():
        for iid, lots in st.lots.items():
            if sum(l.qty for l in lots) > EPS and inst_by_id[iid].price_source != "bond_formula":
                market_dates.update(x for x in market._dates.get(iid, ()) if x <= as_of_s)
    md = sorted(market_dates)
    last_md = md[-1] if md else as_of_s
    prev_md = md[-2] if len(md) > 1 else None
    idx = {ds: i for i, ds in enumerate(dates)}

    def change(series: dict) -> tuple[float, float | None]:
        i, j = idx.get(last_md), idx.get(prev_md) if prev_md else None
        if i is None or j is None:
            return 0.0, None
        diff = (series["gross"][i] - series["gross"][j]) - (series["invested"][i] - series["invested"][j])
        base = series["gross"][j]
        return diff, (diff / base if abs(base) > EPS else None)

    # ---- per-account details at as_of
    by_account = {}
    for a in accounts:
        st = states[a.id]
        v = st.value(as_of_s, market, detailed=True)
        for p in v["positions"]:
            p["weight"] = p["value"] / v["gross"] if abs(v["gross"]) > EPS else None
            if p["price_kind"] in ("feed", "trade") and p["price_date"]:
                p["stale"] = (as_of - date.fromisoformat(p["price_date"])).days > STALE_AFTER_DAYS
                if p["stale"]:
                    warn("price_stale", instrument=p["symbol"], detail=p["price_date"])
            else:
                p["stale"] = False
            if p["price_kind"] == "trade":
                warn("price_from_trade", instrument=p["symbol"])
            if p["price_kind"] == "none":
                warn("price_missing", instrument=p["symbol"])
            p["day_change"] = _position_day_change(p, market, last_md, prev_md)
        retirement = a.kind in RETIREMENT_KINDS
        totals = {
            **{k: v[k] for k in ("gross", "net", "exit_tax", "positions_value", "cash_value", "open_cost",
                                 "liquidation_fees", "invested")},
            "own_contrib": st.own_contrib,
            "employer_contrib": st.employer_contrib,
            "state_contrib": st.state_contrib,
            "realized": st.realized,
            "income": st.income,
            "fees": st.fees,
            "taxes": st.taxes,
            "retirement_gross": v["gross"] if retirement else 0.0,
            "retirement_net": v["net"] if retirement else 0.0,
        }
        _finish_totals(totals, st.flows, as_of, change(hist[a.id]))
        by_account[str(a.id)] = {
            "id": a.id,
            "name": a.name,
            "person_id": a.person_id,
            "kind": a.kind,
            "totals": _round(totals),
            "cash": {k: round(x, 2) for k, x in v["cash"].items()},
            "positions": [_round(p) for p in sorted(v["positions"], key=lambda p: -p["value"])],
            "allocation": _allocation(v),
        }

    # ---- aggregate scopes
    def aggregate(acc_ids: list[int]) -> tuple[dict, dict]:
        totals = {k: sum(by_account[str(i)]["totals"][k] for i in acc_ids) for k in SUM_FIELDS}
        series = {k: [round(sum(hist[i][k][n] for i in acc_ids), 2) for n in range(len(dates))]
                  for k in ("gross", "net", "invested")}
        flows = [f for i in acc_ids for f in states[i].flows]
        _finish_totals(totals, flows, as_of, change(series))
        return _round(totals), series

    by_person = {}
    series_out = {f"account:{a.id}": hist[a.id] for a in accounts}
    for p in persons:
        ids = [a.id for a in accounts if a.person_id == p.id]
        totals, series = aggregate(ids)
        by_person[str(p.id)] = {"id": p.id, "name": p.name, "accounts": ids, "totals": totals,
                                "allocation": _merge_allocations([by_account[str(i)] for i in ids])}
        series_out[f"person:{p.id}"] = series
    all_totals, all_series = aggregate([a.id for a in accounts])
    series_out["all"] = all_series

    fx_latest = {ccy: market.fx(ccy, as_of_s) for ccy in market.fx_ids}
    fx_history = {ccy: [round(market.fx(ccy, ds), 6) for ds in dates] for ccy in market.fx_ids}

    return {
        "dashboard": {
            "as_of": as_of_s,
            "market_date": last_md,
            "prev_market_date": prev_md,
            "fx": {k: round(v, 6) for k, v in fx_latest.items()},
            "totals": all_totals,
            "allocation": _merge_allocations(list(by_account.values())),
            "by_person": by_person,
            "by_account": by_account,
            "warnings": list(warnings.values()),
        },
        "history": {"dates": dates, "series": series_out, "fx": fx_history},
    }


def _position_day_change(p: dict, m: Market, last_md: str, prev_md: str | None) -> float:
    if not prev_md or p["price_kind"] == "bond":
        return 0.0
    now, _, _ = m.price(p["instrument_id"], last_md)
    before, _, _ = m.price(p["instrument_id"], prev_md)
    fx = m.fx(p["currency"], last_md)
    fx_before = m.fx(p["currency"], prev_md)
    return p["quantity"] * (now * fx - before * fx_before)


def _finish_totals(t: dict, flows, as_of: date, day_change: tuple[float, float | None]) -> None:
    t["profit"] = t["gross"] - t["invested"]
    t["profit_pct"] = t["profit"] / t["invested"] if t["invested"] > EPS else None
    t["unrealized"] = t["positions_value"] - t["liquidation_fees"] - t["open_cost"]
    t["day_change"], t["day_change_pct"] = day_change
    t["xirr"] = xirr(list(flows) + [(as_of, t["gross"])]) if t["gross"] > EPS else None


def _allocation(v: dict) -> dict:
    by_class: dict[str, float] = defaultdict(float)
    by_ccy: dict[str, float] = defaultdict(float)
    for p in v["positions"]:
        by_class[p["asset_class"]] += p["value"]
        by_ccy[p["currency"]] += p["value"]
    for ccy, value in v["cash_pln"].items():
        by_class["CASH"] += value
        by_ccy[ccy] += value
    return {"asset_class": _round(dict(by_class)), "currency": _round(dict(by_ccy))}


def _merge_allocations(entries: list[dict]) -> dict:
    out = {"asset_class": defaultdict(float), "currency": defaultdict(float), "account_kind": defaultdict(float)}
    for e in entries:
        for dim in ("asset_class", "currency"):
            for k, v in e["allocation"][dim].items():
                out[dim][k] += v
        out["account_kind"][e["kind"]] += e["totals"]["gross"]
    return {k: _round(dict(v)) for k, v in out.items()}


def _round(obj):
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v) for v in obj]
    return obj
