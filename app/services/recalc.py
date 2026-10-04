"""Glue between the database, the engine, the price providers and the JSON snapshots."""

import threading
import time
from datetime import date, timedelta

from app import db
from app.services import engine, prices, snapshot

_lock = threading.Lock()


def load_inputs(conn):
    persons = [engine.Person(r["id"], r["name"]) for r in conn.execute("SELECT id, name FROM person ORDER BY name")]
    accounts = [
        engine.Account(r["id"], r["person_id"], r["name"], r["kind"], r["currency"])
        for r in conn.execute("SELECT * FROM account ORDER BY person_id, name")
    ]
    instruments = [
        engine.Instrument(r["id"], r["symbol"], r["name"], r["asset_class"], r["currency"], r["price_source"],
                          r["source_config"])
        for r in conn.execute("SELECT * FROM instrument")
    ]
    txns = [
        engine.Txn(
            id=r["id"], account_id=r["account_id"], date=r["date"], type=r["type"], cash_amount=r["cash_amount"],
            cash_currency=r["cash_currency"], instrument_id=r["instrument_id"], quantity=r["quantity"],
            price=r["price"], fee=r["fee"] or 0.0, tax=r["tax"] or 0.0, amount_pln=r["amount_pln"],
            counter_amount=r["counter_amount"], counter_currency=r["counter_currency"],
        )
        for r in conn.execute("SELECT * FROM txn")
    ]
    price_rows: dict[int, list] = {}
    for r in conn.execute("SELECT instrument_id, date, close FROM price ORDER BY instrument_id, date"):
        price_rows.setdefault(r["instrument_id"], []).append((r["date"], r["close"]))
    cpi = {r["month"]: r["yoy"] for r in conn.execute("SELECT month, yoy FROM cpi")}
    return persons, accounts, instruments, txns, price_rows, cpi


def recalculate(conn, snapshot_dir, as_of: date | None = None) -> dict:
    with _lock:
        started = time.monotonic()
        version = db.data_version(conn)
        result = engine.run(*load_inputs(conn), as_of=as_of or date.today())
        meta = {
            "computed_at": db.now_iso(),
            "data_version": version,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        snapshot.write(snapshot_dir, meta, result)
        db.set_state(conn, "last_recalc", meta["computed_at"])
        conn.commit()
        return meta


def refresh_prices(conn, today: date | None = None) -> dict:
    """Download missing daily closes for held instruments and FX pairs from their linked providers."""
    today = today or date.today()
    report = {"updated": [], "failed": [], "skipped": 0, "points": 0}
    rows = conn.execute(
        """
        SELECT i.*, (SELECT MAX(date) FROM price p WHERE p.instrument_id = i.id) AS last_date
        FROM instrument i
        WHERE i.asset_class = 'FX'
           OR i.id IN (SELECT instrument_id FROM txn WHERE instrument_id IS NOT NULL
                       GROUP BY account_id, instrument_id
                       HAVING ABS(SUM(CASE type WHEN 'SELL' THEN -quantity WHEN 'TRANSFER_OUT' THEN -quantity
                                                 WHEN 'BUY' THEN quantity WHEN 'TRANSFER_IN' THEN quantity
                                                 ELSE 0 END)) > 1e-9)
        """
    ).fetchall()
    for inst in rows:
        provider = prices.get(inst["price_source"])
        if provider is None or not provider.fetchable:
            report["skipped"] += 1
            continue
        since = date.fromisoformat(inst["last_date"]) + timedelta(days=1) if inst["last_date"] else None
        try:
            points = provider.fetch(dict(inst), since, today)
        except Exception as exc:  # one bad source must not stop the others
            report["failed"].append({"symbol": inst["symbol"], "error": str(exc)})
            continue
        conn.executemany(
            "INSERT INTO price(instrument_id, date, close, source) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(instrument_id, date) DO UPDATE SET close = excluded.close, source = excluded.source",
            [(inst["id"], p.date, p.close, provider.key) for p in points],
        )
        report["points"] += len(points)
        report["updated"].append(inst["symbol"])
    if report["points"]:
        db.bump_version(conn)
    db.set_state(conn, "last_price_refresh", db.now_iso())
    conn.commit()
    return report
