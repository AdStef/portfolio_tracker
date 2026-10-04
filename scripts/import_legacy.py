"""One-time migration of the old Google-Sheet transaction export and the initial EOD price files.

    python -m scripts.import_legacy --person "Adam"
    python -m scripts.import_legacy --person "Adam" --csv "initial_eod_data/Portfolio_tracker - Transakcje.csv" \
        --eod-dir initial_eod_data --data-dir data

What it does with the legacy quirks:
* cash deposits stored as Liczba=1/Cena=1 use the 'Total PLN' column as the amount;
* 'Waluty_EUR' rows are not an asset any more: PLN->EUR purchases (Cena = 1) become FX_EXCHANGE, the other
  Waluty rows are the EUR cash legs of trades and are used as the exact EUR cash amount of the matching trade;
* PPK 'Dywidenda / Odsetki' rows become EMPLOYER_CONTRIBUTION ('... od Państwa' -> STATE_CONTRIBUTION).
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import build_config  # noqa: E402
from app.parsing import parse_date, parse_number  # noqa: E402
from app.services import bonds, recalc, transactions  # noqa: E402

ACCOUNTS = {
    "PPK": {"kind": "PPK", "currency": "PLN", "broker": None},
    "IKE": {"kind": "IKE", "currency": "PLN", "broker": None},
    "IKZE": {"kind": "IKZE", "currency": "PLN", "broker": None},
    "PKO Obligacje": {"kind": "BONDS", "currency": "PLN", "broker": "PKO BP"},
    "XTB PLN": {"kind": "REGULAR", "currency": "PLN", "broker": "XTB"},
    "XTB EUR": {"kind": "REGULAR", "currency": "EUR", "broker": "XTB"},
}
ETFS = {"WSE:ETFBM40TR", "WSE:ETFBS80TR"}
CLASS_MAP = {
    "Akcje polskie": "STOCK_PL",
    "Akcje zagraniczne": "ETF_EQUITY",
    "Obligacje skarbowe zagraniczne": "ETF_BOND",
    "Obligacje skarbowe polskie": "BOND_GOV_PL",
}
GENERIC_NAMES = {"Gotówka", "Waluty_EUR"}


def source_symbol(symbol: str) -> str | None:
    if symbol.startswith("WSE:"):
        return symbol[4:] + ".WA"
    if symbol.startswith("AMS:"):
        return symbol[4:] + ".AS"
    if symbol.endswith(":DE"):
        return symbol[:-3] + ".DE"
    return None


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for n, r in enumerate(rows, 2):
        r["_line"] = n
        r["_date"] = parse_date(r["Data"])
        for col in ("Liczba", "Cena", "Prowizje", "Kurs PLN transakcji", "Total PLN"):
            r[col] = parse_number(r[col]) or 0.0
    return rows


def build_instruments(rows) -> dict[str, dict]:
    out = {}
    for r in rows:
        sym = r["Ticker"]
        if sym in ("Gotówka", "Waluty_EUR"):
            continue
        inst = out.setdefault(sym, {"symbol": sym, "name": sym, "currency": r["Waluta"]})
        if r["Nazwa"] and r["Nazwa"] not in GENERIC_NAMES and r["Nazwa"] != sym and r["Konto"] != "PPK":
            inst["name"] = r["Nazwa"]
        if sym == "PPK":
            inst.update(asset_class="FUND", name="PPK")
        elif sym in ETFS:
            inst["asset_class"] = "ETF_EQUITY"
        else:
            inst["asset_class"] = CLASS_MAP.get(r["Klasa aktywów"], "OTHER")
    for inst in out.values():
        if bonds.parse_symbol(inst["symbol"]):
            inst.update(price_source="bond_formula", source_symbol=None,
                        source_config='{"series": "%s"}' % bonds.parse_symbol(inst["symbol"])["series"])
        else:
            inst.update(price_source="manual", source_symbol=source_symbol(inst["symbol"]), source_config=None)
    return out


def convert(rows, account_ids, instrument_ids, report) -> list[dict]:
    # EUR cash legs of trades, keyed by (account, date, Total PLN, direction)
    legs = defaultdict(list)
    for r in rows:
        if r["Ticker"] == "Waluty_EUR" and not (r["Rodzaj transakcji"] == "Zakup" and r["Cena"] == 1.0):
            direction = "out" if r["Rodzaj transakcji"] == "Sprzedaż" else "in"
            legs[(r["Konto"], r["_date"], round(r["Total PLN"], 2), direction)].append(r)

    out = []
    for r in rows:
        acc, kind, sym = r["Konto"], r["Rodzaj transakcji"], r["Ticker"]
        base = {"account_id": account_ids[acc], "date": r["_date"], "instrument_id": None, "quantity": None,
                "price": None, "fee": 0.0, "tax": 0.0, "amount_pln": None, "counter_amount": None,
                "counter_currency": None, "note": r.get("Komentarz") or None}
        total = abs(r["Total PLN"])
        if sym == "Gotówka":
            t = "DEPOSIT" if kind == "Wpłata środków" else "WITHDRAWAL"
            out.append({**base, "type": t, "cash_amount": total if t == "DEPOSIT" else -total, "cash_currency": "PLN",
                        "amount_pln": total})
        elif sym == "Waluty_EUR":
            if kind == "Zakup" and r["Cena"] == 1.0:
                out.append({**base, "type": "FX_EXCHANGE", "cash_amount": -total, "cash_currency": "PLN",
                            "counter_amount": r["Liczba"], "counter_currency": "EUR", "amount_pln": total})
            # other Waluty rows are consumed as trade legs below
        elif kind in ("Zakup", "Sprzedaż"):
            t = "BUY" if kind == "Zakup" else "SELL"
            qty, price, fee = r["Liczba"], r["Cena"], r["Prowizje"]
            cash_ccy = ACCOUNTS[acc]["currency"]
            if cash_ccy == "EUR":
                key = (acc, r["_date"], round(r["Total PLN"], 2), "out" if t == "BUY" else "in")
                if legs.get(key):
                    eur = legs[key].pop(0)["Liczba"]
                else:
                    eur = qty * price
                    if eur:
                        report["unmatched_trades"].append(r["_line"])
                cash = -eur if t == "BUY" else eur
            else:
                cash = -total if t == "BUY" else total
            out.append({**base, "type": t, "instrument_id": instrument_ids[sym], "quantity": qty, "price": price,
                        "fee": fee, "cash_amount": cash, "cash_currency": cash_ccy, "amount_pln": total})
        elif kind == "Dywidenda / Odsetki":
            if acc == "PPK":
                t = "STATE_CONTRIBUTION" if "Państwa" in r["Nazwa"] else "EMPLOYER_CONTRIBUTION"
                out.append({**base, "type": t, "cash_amount": total, "cash_currency": "PLN", "amount_pln": total,
                            "note": base["note"] or r["Nazwa"]})
            else:
                t = "INTEREST" if r["Klasa aktywów"].startswith("Obligacje") else "DIVIDEND"
                out.append({**base, "type": t, "instrument_id": instrument_ids.get(sym), "cash_amount": total,
                            "cash_currency": "PLN", "amount_pln": total})
        else:
            report["skipped"].append((r["_line"], kind))
    report["unused_legs"] = sum(len(v) for v in legs.values())
    return out


def load_eod(conn, eod_dir: Path, instruments_by_source: dict[str, int]) -> dict[str, int]:
    counts = {}
    for path in sorted(eod_dir.glob("*_data.csv")):
        key = path.name[: -len("_data.csv")]
        iid = instruments_by_source.get(key)
        if iid is None:
            counts[key] = 0
            continue
        with path.open(encoding="utf-8") as f:
            points = [(iid, parse_date(r["DATE"]), parse_number(r["CLOSE"]), "legacy_eod") for r in csv.DictReader(f)]
        conn.executemany("INSERT OR REPLACE INTO price(instrument_id, date, close, source) VALUES (?, ?, ?, ?)", points)
        counts[key] = len(points)
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--person", required=True, help="owner of all legacy accounts")
    ap.add_argument("--csv", default=str(ROOT / "initial_eod_data" / "Portfolio_tracker - Transakcje.csv"))
    ap.add_argument("--eod-dir", default=str(ROOT / "initial_eod_data"))
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-recalc", action="store_true")
    args = ap.parse_args(argv)

    cfg = build_config(args.data_dir)
    db.init_db(cfg["DATABASE"])
    conn = db.connect(cfg["DATABASE"])
    if conn.execute("SELECT 1 FROM person WHERE name = ?", (args.person,)).fetchone():
        sys.exit(f"person {args.person!r} already exists - migration was already run (delete data/ to start over)")

    rows = load_rows(Path(args.csv))
    report = {"unmatched_trades": [], "skipped": []}
    with conn:
        person_id = conn.execute("INSERT INTO person(name) VALUES (?)", (args.person,)).lastrowid
        account_ids = {}
        for name in sorted({r["Konto"] for r in rows}):
            spec = ACCOUNTS.get(name, {"kind": "REGULAR", "currency": "PLN", "broker": None})
            account_ids[name] = conn.execute(
                "INSERT INTO account(person_id, name, broker, kind, currency) VALUES (?, ?, ?, ?, ?)",
                (person_id, name, spec["broker"], spec["kind"], spec["currency"])).lastrowid

        instrument_ids, by_source = {}, {}
        for sym, inst in build_instruments(rows).items():
            existing = conn.execute("SELECT id FROM instrument WHERE symbol = ?", (sym,)).fetchone()
            instrument_ids[sym] = existing["id"] if existing else transactions.create_instrument(conn, inst)
            if inst.get("source_symbol"):
                by_source[inst["source_symbol"]] = instrument_ids[sym]
        for pair, name in (("EURPLN", "EUR/PLN"), ("USDPLN", "USD/PLN")):
            row = conn.execute("SELECT id FROM instrument WHERE symbol = ?", (pair,)).fetchone()
            by_source[pair] = row["id"] if row else transactions.create_instrument(
                conn, {"symbol": pair, "name": name, "asset_class": "FX", "currency": "PLN",
                       "price_source": "manual", "source_symbol": pair + "=X"})

        txns = convert(rows, account_ids, instrument_ids, report)
        for t in txns:
            transactions.insert(conn, t)
        prices = load_eod(conn, Path(args.eod_dir), by_source)
        db.bump_version(conn)

    print(f"person: {args.person}")
    print(f"accounts: {', '.join(account_ids)}")
    print(f"instruments: {len(instrument_ids)} (+ EURPLN, USDPLN)")
    print(f"legacy rows: {len(rows)} -> transactions: {len(txns)}")
    print(f"price files: " + ", ".join(f"{k}={v}" for k, v in prices.items()))
    if report["unmatched_trades"]:
        print(f"WARNING: EUR trades without a Waluty_EUR cash leg (used qty*price) on lines {report['unmatched_trades']}")
    if report["unused_legs"]:
        print(f"WARNING: {report['unused_legs']} Waluty_EUR cash legs did not match any trade")
    if report["skipped"]:
        print(f"WARNING: skipped rows {report['skipped']}")

    legacy_eur = sum((r["Liczba"] if r["Rodzaj transakcji"] == "Zakup" else -r["Liczba"])
                     for r in rows if r["Ticker"] == "Waluty_EUR")
    new_eur = conn.execute("SELECT SUM(cash_amount) FROM txn WHERE cash_currency = 'EUR'").fetchone()[0] or 0
    new_eur += conn.execute("SELECT SUM(counter_amount) FROM txn WHERE counter_currency = 'EUR'").fetchone()[0] or 0
    print(f"check: EUR cash legacy={legacy_eur:.2f} migrated={new_eur:.2f}")

    if not args.no_recalc:
        meta = recalc.recalculate(conn, cfg["SNAPSHOT_DIR"], date.today())
        print(f"snapshot written in {meta['duration_ms']} ms")
    conn.close()


if __name__ == "__main__":
    main()
