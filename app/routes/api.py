import json
import sqlite3
from datetime import date

from flask import Blueprint, Response, current_app, jsonify, request

from app import db
from app.constants import ACCOUNT_KINDS, ASSET_CLASSES
from app.db import get_db
from app.parsing import parse_date, parse_number
from app.services import bonds, csv_import, prices, recalc, snapshot, transactions
from app.services.importers import IMPORTERS
from app.services.importers.native import TEMPLATE

bp = Blueprint("api", __name__)


class ApiError(Exception):
    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.status = status
        self.errors = errors or [message]


@bp.errorhandler(ApiError)
def _api_error(exc):
    return jsonify({"ok": False, "errors": exc.errors}), exc.status


@bp.errorhandler(transactions.ValidationError)
def _validation_error(exc):
    return jsonify({"ok": False, "errors": exc.errors}), 400


@bp.errorhandler(sqlite3.IntegrityError)
def _integrity_error(exc):
    return jsonify({"ok": False, "errors": [f"database constraint: {exc}"]}), 409


def _body() -> dict:
    return request.get_json(silent=True) or request.form.to_dict()


def _snapshot_dir():
    return current_app.config["SNAPSHOT_DIR"]


# ------------------------------------------------------------------ dashboard


@bp.get("/dashboard")
def dashboard():
    conn = get_db()
    data = snapshot.read(_snapshot_dir(), "dashboard")
    version = db.data_version(conn)
    return jsonify({
        "snapshot": data,
        "data_version": version,
        "stale": data is None or data["meta"].get("data_version") != version,
        "last_price_refresh": db.get_state(conn, "last_price_refresh"),
    })


@bp.get("/history")
def history():
    data = snapshot.read(_snapshot_dir(), "history")
    if data is None:
        return jsonify({"dates": [], "series": {}, "fx": {}})
    scope = request.args.get("scope", "all")
    return jsonify({"meta": data["meta"], "dates": data["dates"], "fx": data["fx"],
                    "series": data["series"].get(scope, {})})


@bp.post("/recalculate")
def recalculate():
    meta = recalc.recalculate(get_db(), _snapshot_dir())
    return jsonify({"ok": True, "meta": meta})


@bp.post("/prices/refresh")
def refresh_prices():
    conn = get_db()
    report = recalc.refresh_prices(conn)
    meta = recalc.recalculate(conn, _snapshot_dir())
    return jsonify({"ok": True, "report": report, "meta": meta})


# ------------------------------------------------------------------ transactions


@bp.get("/transactions")
def list_transactions():
    rows = _query_transactions(request.args)
    return jsonify([dict(r) for r in rows])


def _query_transactions(args, limit=None, offset=0):
    where, params = [], []
    if args.get("person_id"):
        where.append("a.person_id = ?")
        params.append(int(args["person_id"]))
    if args.get("account_id"):
        where.append("t.account_id = ?")
        params.append(int(args["account_id"]))
    if args.get("type"):
        where.append("t.type = ?")
        params.append(args["type"])
    if args.get("instrument_id"):
        where.append("t.instrument_id = ?")
        params.append(int(args["instrument_id"]))
    sql = (
        "SELECT t.*, a.name AS account_name, p.name AS person_name, i.symbol, i.name AS instrument_name "
        "FROM txn t JOIN account a ON a.id = t.account_id JOIN person p ON p.id = a.person_id "
        "LEFT JOIN instrument i ON i.id = t.instrument_id"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY t.date DESC, t.id DESC"
    )
    if limit:
        sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return get_db().execute(sql, params).fetchall()


@bp.post("/transactions")
def create_transaction():
    conn = get_db()
    row = transactions.normalize(conn, _body(), create_instruments=True)
    txn_id = transactions.insert(conn, row)
    conn.commit()
    return jsonify({"ok": True, "id": txn_id}), 201


@bp.put("/transactions/<int:txn_id>")
def update_transaction(txn_id):
    conn = get_db()
    if not conn.execute("SELECT 1 FROM txn WHERE id = ?", (txn_id,)).fetchone():
        raise ApiError("not found", 404)
    row = transactions.normalize(conn, _body(), create_instruments=True)
    transactions.update(conn, txn_id, row)
    conn.commit()
    return jsonify({"ok": True, "id": txn_id})


@bp.delete("/transactions/<int:txn_id>")
def delete_transaction(txn_id):
    conn = get_db()
    transactions.delete(conn, txn_id)
    conn.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ import


@bp.get("/import/template.csv")
def import_template():
    return Response(TEMPLATE, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=transactions_template.csv"})


@bp.post("/import/preview")
def import_preview():
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError("no file")
    try:
        result = csv_import.preview(get_db(), current_app.config["IMPORT_DIR"], upload.read(), upload.filename,
                                    request.form.get("profile", "native"), _int_or_none(request.form.get("account_id")))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return jsonify({"ok": True, **result})


@bp.post("/import/commit")
def import_commit():
    body = _body()
    try:
        result = csv_import.commit(get_db(), current_app.config["IMPORT_DIR"], body.get("token"),
                                   body.get("profile", "native"), _int_or_none(body.get("account_id")))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return jsonify({"ok": True, **result})


@bp.delete("/import/<int:batch_id>")
def import_undo(batch_id):
    return jsonify({"ok": True, "deleted": csv_import.undo(get_db(), batch_id)})


# ------------------------------------------------------------------ people & accounts


@bp.post("/people")
def create_person():
    body = _body()
    name = (body.get("name") or "").strip()
    if not name:
        raise ApiError("name is required")
    conn = get_db()
    cur = conn.execute("INSERT INTO person(name, color) VALUES (?, ?)", (name, body.get("color") or None))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@bp.put("/people/<int:person_id>")
def update_person(person_id):
    body = _body()
    conn = get_db()
    conn.execute("UPDATE person SET name = ?, color = ? WHERE id = ?",
                 (body.get("name"), body.get("color") or None, person_id))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


@bp.delete("/people/<int:person_id>")
def delete_person(person_id):
    conn = get_db()
    if conn.execute("SELECT 1 FROM account WHERE person_id = ?", (person_id,)).fetchone():
        raise ApiError("person still has accounts", 409)
    conn.execute("DELETE FROM person WHERE id = ?", (person_id,))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


def _account_values(body):
    kind = (body.get("kind") or "REGULAR").upper()
    if kind not in ACCOUNT_KINDS:
        raise ApiError(f"unknown account kind {kind}")
    name = (body.get("name") or "").strip()
    if not name or not body.get("person_id"):
        raise ApiError("name and person are required")
    return {
        "person_id": int(body["person_id"]),
        "name": name,
        "broker": (body.get("broker") or "").strip() or None,
        "kind": kind,
        "currency": (body.get("currency") or "PLN").upper(),
        "archived": 1 if str(body.get("archived", "")).lower() in ("1", "true", "on") else 0,
        "note": body.get("note") or None,
    }


@bp.post("/accounts")
def create_account():
    conn = get_db()
    v = _account_values(_body())
    cur = conn.execute(
        "INSERT INTO account(person_id, name, broker, kind, currency, archived, note) "
        "VALUES (:person_id, :name, :broker, :kind, :currency, :archived, :note)", v)
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@bp.put("/accounts/<int:account_id>")
def update_account(account_id):
    conn = get_db()
    v = _account_values(_body())
    conn.execute(
        "UPDATE account SET person_id = :person_id, name = :name, broker = :broker, kind = :kind, "
        "currency = :currency, archived = :archived, note = :note WHERE id = :id", {**v, "id": account_id})
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


@bp.delete("/accounts/<int:account_id>")
def delete_account(account_id):
    conn = get_db()
    if conn.execute("SELECT 1 FROM txn WHERE account_id = ?", (account_id,)).fetchone():
        raise ApiError("account has transactions; archive it instead", 409)
    conn.execute("DELETE FROM account WHERE id = ?", (account_id,))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ instruments & prices


def _instrument_values(body):
    symbol = (body.get("symbol") or "").strip()
    if not symbol:
        raise ApiError("symbol is required")
    asset_class = (body.get("asset_class") or "OTHER").upper()
    if asset_class not in ASSET_CLASSES:
        raise ApiError(f"unknown asset class {asset_class}")
    source = body.get("price_source") or "manual"
    if prices.get(source) is None:
        raise ApiError(f"unknown price source {source}")
    config = body.get("source_config")
    if isinstance(config, dict):
        config = json.dumps(config)
    config = (config or "").strip() or None
    if config:
        try:
            json.loads(config)
        except ValueError as exc:
            raise ApiError(f"source config is not valid JSON: {exc}") from exc
    return {
        "symbol": symbol,
        "name": (body.get("name") or "").strip() or symbol,
        "asset_class": asset_class,
        "currency": (body.get("currency") or "PLN").upper(),
        "price_source": source,
        "source_symbol": (body.get("source_symbol") or "").strip() or None,
        "source_config": config,
        "note": body.get("note") or None,
    }


@bp.post("/instruments")
def create_instrument():
    conn = get_db()
    v = _instrument_values(_body())
    cur = conn.execute(
        "INSERT INTO instrument(symbol, name, asset_class, currency, price_source, source_symbol, source_config, note)"
        " VALUES (:symbol, :name, :asset_class, :currency, :price_source, :source_symbol, :source_config, :note)", v)
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True, "id": cur.lastrowid}), 201


@bp.put("/instruments/<int:instrument_id>")
def update_instrument(instrument_id):
    conn = get_db()
    v = _instrument_values(_body())
    conn.execute(
        "UPDATE instrument SET symbol = :symbol, name = :name, asset_class = :asset_class, currency = :currency, "
        "price_source = :price_source, source_symbol = :source_symbol, source_config = :source_config, note = :note "
        "WHERE id = :id", {**v, "id": instrument_id})
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


@bp.delete("/instruments/<int:instrument_id>")
def delete_instrument(instrument_id):
    conn = get_db()
    if conn.execute("SELECT 1 FROM txn WHERE instrument_id = ?", (instrument_id,)).fetchone():
        raise ApiError("instrument is used by transactions", 409)
    conn.execute("DELETE FROM instrument WHERE id = ?", (instrument_id,))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


@bp.put("/instruments/<int:instrument_id>/bond")
def update_bond_params(instrument_id):
    """Merges bond fields from the form into source_config."""
    conn = get_db()
    inst = conn.execute("SELECT * FROM instrument WHERE id = ?", (instrument_id,)).fetchone()
    if inst is None:
        raise ApiError("not found", 404)
    body = _body()
    cfg = json.loads(inst["source_config"] or "{}")
    try:
        for key in ("first_rate", "margin", "fee"):
            if key in body:
                value = parse_number(body[key])
                if value is None:
                    cfg.pop(key, None)
                else:
                    cfg[key] = value
        if body.get("series"):
            cfg["series"] = body["series"].upper()
        if "purchase_date" in body:
            if body["purchase_date"]:
                cfg["purchase_date"] = parse_date(body["purchase_date"])
            else:
                cfg.pop("purchase_date", None)
        if "period_rates" in body:
            rates = {}
            for part in str(body["period_rates"] or "").replace(";", ",").split(","):
                if part.strip():
                    n, rate = part.split("=")
                    rates[str(int(n))] = parse_number(rate)
            cfg["period_rates"] = rates
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    if bonds.load_params(inst["symbol"], cfg) is None:
        raise ApiError("unknown series or purchase date; use a symbol like EDO-100134 or set both")
    conn.execute("UPDATE instrument SET source_config = ?, price_source = 'bond_formula' WHERE id = ?",
                 (json.dumps(cfg), instrument_id))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


@bp.get("/instruments/<int:instrument_id>/bond-preview")
def bond_preview(instrument_id):
    """Value of one bond today under the saved parameters, to sanity-check them."""
    conn = get_db()
    inst = conn.execute("SELECT * FROM instrument WHERE id = ?", (instrument_id,)).fetchone()
    params = bonds.load_params(inst["symbol"], inst["source_config"]) if inst else None
    if params is None:
        raise ApiError("not a bond or parameters missing")
    on = date.fromisoformat(request.args["date"]) if request.args.get("date") else date.today()
    cpi = {r["month"]: r["yoy"] for r in conn.execute("SELECT month, yoy FROM cpi")}
    bv = bonds.value_on(params, on, cpi)
    return jsonify({"date": on.isoformat(), "purchase_date": params.purchase_date.isoformat(),
                    "maturity": params.maturity.isoformat(), **bv.__dict__})


@bp.post("/instruments/<int:instrument_id>/prices")
def add_price(instrument_id):
    """Manual price. Either `close` (per unit) or `total_value` (whole holding -> divided by held quantity)."""
    body = _body()
    conn = get_db()
    try:
        on = parse_date(body.get("date"))
        close = parse_number(body.get("close"))
        total = parse_number(body.get("total_value"))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    if close is None and total is not None:
        qty = conn.execute(
            "SELECT SUM(CASE type WHEN 'BUY' THEN quantity WHEN 'TRANSFER_IN' THEN quantity "
            "WHEN 'SELL' THEN -quantity WHEN 'TRANSFER_OUT' THEN -quantity ELSE 0 END) "
            "FROM txn WHERE instrument_id = ? AND date <= ?", (instrument_id, on)).fetchone()[0]
        if not qty:
            raise ApiError("nothing held on that date, enter a unit price")
        close = total / qty
    if close is None or close < 0:
        raise ApiError("price is required")
    conn.execute(
        "INSERT INTO price(instrument_id, date, close, source) VALUES (?, ?, ?, 'manual') "
        "ON CONFLICT(instrument_id, date) DO UPDATE SET close = excluded.close, source = 'manual'",
        (instrument_id, on, close))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True, "close": close}), 201


@bp.delete("/instruments/<int:instrument_id>/prices/<day>")
def delete_price(instrument_id, day):
    conn = get_db()
    conn.execute("DELETE FROM price WHERE instrument_id = ? AND date = ?", (instrument_id, day))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ CPI


@bp.post("/cpi")
def upsert_cpi():
    """Body: {"text": "2024-11;4.7\\n2024-12;4,7"} (one month per line) or {"month": .., "yoy": ..}."""
    body = _body()
    lines = body.get("text") or f"{body.get('month', '')};{body.get('yoy', '')}"
    rows, errors = [], []
    for n, line in enumerate(str(lines).splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace("\t", ";").split(";")]
        if len(parts) != 2 or len(parts[0]) != 7:
            errors.append(f"line {n}: expected YYYY-MM;value")
            continue
        try:
            rows.append((parts[0], parse_number(parts[1])))
        except ValueError as exc:
            errors.append(f"line {n}: {exc}")
    if errors:
        raise ApiError("invalid CPI data", errors=errors)
    conn = get_db()
    conn.executemany("INSERT INTO cpi(month, yoy) VALUES (?, ?) "
                     "ON CONFLICT(month) DO UPDATE SET yoy = excluded.yoy", rows)
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True, "saved": len(rows)})


@bp.delete("/cpi/<month>")
def delete_cpi(month):
    conn = get_db()
    conn.execute("DELETE FROM cpi WHERE month = ?", (month,))
    db.bump_version(conn)
    conn.commit()
    return jsonify({"ok": True})


# ------------------------------------------------------------------ SQL console


@bp.post("/sql")
def run_sql():
    query = (_body().get("query") or "").strip()
    if not query:
        raise ApiError("empty query")
    uri = f"file:{current_app.config['DATABASE']}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(query)
        columns = [c[0] for c in cur.description or []]
        rows = cur.fetchmany(1000)
    except sqlite3.Error as exc:
        raise ApiError(str(exc)) from exc
    finally:
        conn.close()
    return jsonify({"ok": True, "columns": columns, "rows": rows, "truncated": len(rows) == 1000})


@bp.get("/meta")
def meta():
    return jsonify({
        "importers": [{"key": i.key, "label": i.label, "single_account": i.single_account}
                      for i in IMPORTERS.values()],
        "price_sources": [{"key": p.key, "label": p.label, "fetchable": p.fetchable}
                          for p in prices.PROVIDERS.values()],
    })


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None
