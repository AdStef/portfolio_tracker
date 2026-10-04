"""Validation and persistence of transactions. Used by the form, the CSV importers and the legacy migration."""

from __future__ import annotations

import hashlib
import json

from app import db
from app.constants import ASSET_CLASSES, BASE_CURRENCY, TXN_TYPES
from app.parsing import parse_date, parse_number
from app.services import bonds

POSITIVE_TYPES = {"DEPOSIT", "TRANSFER_IN", "EMPLOYER_CONTRIBUTION", "STATE_CONTRIBUTION"}
NEGATIVE_TYPES = {"WITHDRAWAL", "TRANSFER_OUT", "FEE", "TAX"}
NEEDS_INSTRUMENT = {"BUY", "SELL"}

COLUMNS = ("account_id", "date", "type", "instrument_id", "quantity", "price", "fee", "tax", "cash_amount",
           "cash_currency", "amount_pln", "counter_amount", "counter_currency", "note")


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def normalize(conn, data: dict, *, create_instruments: bool = False) -> dict:
    """Turns loosely-typed input (form fields or a parsed CSV row) into a complete txn row.

    Accepted keys: account_id | (account [+ person]), date, type, symbol | instrument_id, instrument_name,
    instrument_currency, asset_class, quantity, price, fee, tax, amount (cash effect, sign optional),
    cash_currency, fx_rate (instrument -> cash currency), amount_pln, counter_amount, counter_currency, note.
    """
    errors: list[str] = []
    out: dict = {}

    def num(key):
        try:
            return parse_number(data.get(key))
        except ValueError as exc:
            errors.append(f"{key}: {exc}")
            return None

    # account
    account = _resolve_account(conn, data, errors)
    out["account_id"] = account["id"] if account else None

    try:
        out["date"] = parse_date(data.get("date"))
    except ValueError as exc:
        errors.append(str(exc))

    ttype = str(data.get("type") or "").strip().upper()
    if ttype not in TXN_TYPES:
        errors.append(f"unknown type {ttype!r}")
    out["type"] = ttype

    # instrument
    out["instrument_id"] = None
    new_instrument = None
    symbol = str(data.get("symbol") or "").strip()
    if data.get("instrument_id"):
        out["instrument_id"] = int(data["instrument_id"])
        inst = conn.execute("SELECT * FROM instrument WHERE id = ?", (out["instrument_id"],)).fetchone()
        if inst is None:
            errors.append("unknown instrument")
    elif symbol:
        inst = conn.execute("SELECT * FROM instrument WHERE symbol = ?", (symbol,)).fetchone()
        if inst is None:
            new_instrument = instrument_defaults(symbol, data, account)
            if create_instruments and not errors:
                out["instrument_id"] = create_instrument(conn, new_instrument)
                inst = conn.execute("SELECT * FROM instrument WHERE id = ?", (out["instrument_id"],)).fetchone()
        else:
            out["instrument_id"] = inst["id"]
    else:
        inst = None
    if ttype in NEEDS_INSTRUMENT and not (inst or new_instrument):
        errors.append("instrument is required")
    inst_currency = (inst["currency"] if inst else (new_instrument or {}).get("currency")) or BASE_CURRENCY

    qty, price, fee, tax = num("quantity"), num("price"), num("fee") or 0.0, num("tax") or 0.0
    amount, fx_rate, amount_pln = num("amount"), num("fx_rate"), num("amount_pln")
    counter_amount = num("counter_amount")
    cash_currency = str(data.get("cash_currency") or (account["currency"] if account else BASE_CURRENCY)).upper()

    if ttype in NEEDS_INSTRUMENT:
        if not qty or qty <= 0:
            errors.append("quantity must be > 0")
        if price is None or price < 0:
            errors.append("price is required")
    if ttype in NEEDS_INSTRUMENT and amount is None and qty and price is not None:
        rate = fx_rate or (1.0 if inst_currency == cash_currency else _stored_cross_rate(
            conn, inst_currency, cash_currency, out.get("date")))
        if rate is None:
            errors.append(f"no {inst_currency}->{cash_currency} rate stored for this date; enter amount or FX rate")
        else:
            gross = qty * price * rate
            amount = -(gross + fee + tax) if ttype == "BUY" else gross - fee - tax
    if amount is None:
        in_kind_transfer = ttype in ("TRANSFER_IN", "TRANSFER_OUT") and (inst or new_instrument)
        if not in_kind_transfer and ttype not in NEEDS_INSTRUMENT:  # BUY/SELL already reported above
            errors.append("amount is required")
        amount = 0.0
    if ttype in POSITIVE_TYPES:
        amount = abs(amount)
    elif ttype in NEGATIVE_TYPES or ttype == "BUY":
        amount = -abs(amount)
    elif ttype == "SELL":
        amount = abs(amount)

    out.update(quantity=qty, price=price, fee=abs(fee), tax=abs(tax), cash_amount=round(amount, 6),
               cash_currency=cash_currency, amount_pln=abs(amount_pln) if amount_pln is not None else None,
               counter_amount=None, counter_currency=None)
    if ttype == "FX_EXCHANGE":
        out["cash_amount"] = -abs(amount)
        out["counter_currency"] = str(data.get("counter_currency") or "").upper() or None
        if not out["counter_currency"] or counter_amount is None:
            errors.append("FX exchange needs the received amount and currency")
        elif out["counter_currency"] == cash_currency:
            errors.append("FX exchange needs two different currencies")
        else:
            out["counter_amount"] = abs(counter_amount)
    if ttype in ("FX_EXCHANGE", "DEPOSIT", "WITHDRAWAL", "FEE", "TAX", "EMPLOYER_CONTRIBUTION",
                 "STATE_CONTRIBUTION") and not symbol and not data.get("instrument_id"):
        out["instrument_id"] = None
    out["note"] = (str(data.get("note") or "").strip() or None)

    if errors:
        raise ValidationError(errors)
    out["_new_instrument"] = new_instrument
    return out


def _resolve_account(conn, data, errors):
    if data.get("account_id"):
        row = conn.execute("SELECT * FROM account WHERE id = ?", (int(data["account_id"]),)).fetchone()
        if row is None:
            errors.append("unknown account")
        return row
    name = str(data.get("account") or "").strip()
    if not name:
        errors.append("account is required")
        return None
    person = str(data.get("person") or "").strip()
    if person:
        rows = conn.execute(
            "SELECT a.* FROM account a JOIN person p ON p.id = a.person_id WHERE a.name = ? AND p.name = ?",
            (name, person),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM account WHERE name = ?", (name,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    errors.append(f"account {name!r} not found" if not rows else f"account {name!r} is ambiguous; add person")
    return None


def _stored_cross_rate(conn, from_ccy, to_ccy, on):
    def to_pln(ccy):
        if ccy == BASE_CURRENCY:
            return 1.0
        row = conn.execute(
            "SELECT p.close FROM price p JOIN instrument i ON i.id = p.instrument_id "
            "WHERE i.symbol = ? AND p.date <= ? ORDER BY p.date DESC LIMIT 1",
            (ccy + BASE_CURRENCY, on or "9999"),
        ).fetchone()
        return row["close"] if row else None

    a, b = to_pln(from_ccy), to_pln(to_ccy)
    return a / b if a and b else None


def instrument_defaults(symbol: str, data: dict, account) -> dict:
    bond = bonds.parse_symbol(symbol)
    asset_class = str(data.get("asset_class") or "").upper()
    return {
        "symbol": symbol,
        "name": data.get("instrument_name") or symbol,
        "asset_class": "BOND_GOV_PL" if bond else (asset_class if asset_class in ASSET_CLASSES else "OTHER"),
        "currency": str(data.get("instrument_currency") or data.get("cash_currency")
                        or (account["currency"] if account else BASE_CURRENCY)).upper(),
        "price_source": "bond_formula" if bond else "manual",
        "source_symbol": None,
        "source_config": json.dumps({"series": bond["series"]}) if bond else None,
    }


def create_instrument(conn, inst: dict) -> int:
    cur = conn.execute(
        "INSERT INTO instrument(symbol, name, asset_class, currency, price_source, source_symbol, source_config) "
        "VALUES (:symbol, :name, :asset_class, :currency, :price_source, :source_symbol, :source_config)",
        {"source_symbol": None, "source_config": None, **inst},
    )
    db.bump_version(conn)
    return cur.lastrowid


def base_hash(row: dict) -> str:
    key = "|".join(str(row.get(k)) for k in ("account_id", "date", "type", "instrument_id", "quantity", "price",
                                             "cash_amount", "cash_currency", "counter_amount"))
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def next_free_hash(conn, row: dict) -> str:
    base = base_hash(row)
    n = conn.execute("SELECT COUNT(*) FROM txn WHERE dedupe_hash LIKE ?", (base + "#%",)).fetchone()[0]
    return f"{base}#{n}"


def insert(conn, row: dict, *, dedupe_hash: str | None = None, batch_id: int | None = None) -> int:
    values = {k: row.get(k) for k in COLUMNS}
    values.update(dedupe_hash=dedupe_hash or next_free_hash(conn, row), import_batch_id=batch_id,
                  created_at=db.now_iso())
    cols = ", ".join(values)
    cur = conn.execute(f"INSERT INTO txn({cols}) VALUES ({', '.join(':' + c for c in values)})", values)
    db.bump_version(conn)
    return cur.lastrowid


def update(conn, txn_id: int, row: dict) -> None:
    values = {k: row.get(k) for k in COLUMNS}
    sets = ", ".join(f"{k} = :{k}" for k in values)
    conn.execute(f"UPDATE txn SET {sets} WHERE id = :id", {**values, "id": txn_id})
    db.bump_version(conn)


def delete(conn, txn_id: int) -> None:
    conn.execute("DELETE FROM txn WHERE id = ?", (txn_id,))
    db.bump_version(conn)
