import math

from flask import Blueprint, abort, render_template, request

from app.constants import ACCOUNT_KINDS, ASSET_CLASSES, DISPLAY_CURRENCIES, TXN_TYPES
from app.db import get_db
from app.routes.api import _query_transactions
from app.services import bonds, prices
from app.services.importers import IMPORTERS

bp = Blueprint("pages", __name__)
PAGE_SIZE = 100


def _people_accounts():
    conn = get_db()
    people = conn.execute("SELECT * FROM person ORDER BY name").fetchall()
    accounts = conn.execute(
        "SELECT a.*, p.name AS person_name, (SELECT COUNT(*) FROM txn t WHERE t.account_id = a.id) AS txn_count "
        "FROM account a JOIN person p ON p.id = a.person_id ORDER BY p.name, a.archived, a.name"
    ).fetchall()
    return people, accounts


@bp.get("/")
def dashboard():
    people, accounts = _people_accounts()
    return render_template("dashboard.html", page="dashboard", people=people, accounts=accounts)


@bp.get("/holdings")
def holdings():
    people, accounts = _people_accounts()
    return render_template("holdings.html", page="holdings", people=people, accounts=accounts)


@bp.get("/transactions")
def transactions_page():
    people, accounts = _people_accounts()
    page = max(1, request.args.get("page", 1, type=int))
    rows = _query_transactions(request.args, limit=PAGE_SIZE + 1, offset=(page - 1) * PAGE_SIZE)
    instruments = get_db().execute("SELECT id, symbol FROM instrument ORDER BY symbol").fetchall()
    return render_template("transactions.html", page="transactions", people=people, accounts=accounts,
                           rows=rows[:PAGE_SIZE], has_next=len(rows) > PAGE_SIZE, page_no=page,
                           instruments=instruments, txn_types=TXN_TYPES, args=request.args)


@bp.get("/transactions/new")
@bp.get("/transactions/<int:txn_id>/edit")
def transaction_form(txn_id=None):
    conn = get_db()
    _, accounts = _people_accounts()
    txn = None
    if txn_id:
        txn = conn.execute("SELECT t.*, i.symbol FROM txn t LEFT JOIN instrument i ON i.id = t.instrument_id "
                           "WHERE t.id = ?", (txn_id,)).fetchone()
        if txn is None:
            abort(404)
    instruments = conn.execute("SELECT symbol, name, currency FROM instrument WHERE asset_class != 'FX' "
                               "ORDER BY symbol").fetchall()
    return render_template("transaction_form.html", page="transactions", txn=txn, accounts=accounts,
                           instruments=instruments, txn_types=TXN_TYPES, asset_classes=ASSET_CLASSES,
                           currencies=DISPLAY_CURRENCIES)


@bp.get("/import")
def import_page():
    _, accounts = _people_accounts()
    batches = get_db().execute("SELECT * FROM import_batch ORDER BY id DESC LIMIT 50").fetchall()
    return render_template("import.html", page="transactions", accounts=accounts, importers=IMPORTERS.values(),
                           batches=batches)


@bp.get("/accounts")
def accounts_page():
    people, accounts = _people_accounts()
    return render_template("accounts.html", page="accounts", people=people, accounts=accounts,
                           kinds=ACCOUNT_KINDS, currencies=DISPLAY_CURRENCIES)


@bp.get("/instruments")
def instruments_page():
    conn = get_db()
    rows = conn.execute(
        "SELECT i.*, (SELECT close FROM price p WHERE p.instrument_id = i.id ORDER BY date DESC LIMIT 1) AS last_close,"
        " (SELECT MAX(date) FROM price p WHERE p.instrument_id = i.id) AS last_date,"
        " (SELECT COUNT(*) FROM txn t WHERE t.instrument_id = i.id) AS txn_count "
        "FROM instrument i ORDER BY i.asset_class = 'FX', i.symbol"
    ).fetchall()
    cpi = conn.execute("SELECT * FROM cpi ORDER BY month DESC").fetchall()
    return render_template("instruments.html", page="instruments", rows=rows, cpi=cpi,
                           asset_classes=ASSET_CLASSES, providers=prices.PROVIDERS.values())


@bp.get("/instruments/<int:instrument_id>")
def instrument_page(instrument_id):
    conn = get_db()
    inst = conn.execute("SELECT * FROM instrument WHERE id = ?", (instrument_id,)).fetchone()
    if inst is None:
        abort(404)
    price_rows = conn.execute("SELECT * FROM price WHERE instrument_id = ? ORDER BY date DESC LIMIT 200",
                              (instrument_id,)).fetchall()
    price_count = conn.execute("SELECT COUNT(*) FROM price WHERE instrument_id = ?", (instrument_id,)).fetchone()[0]
    bond = bonds.load_params(inst["symbol"], inst["source_config"]) if inst["price_source"] == "bond_formula" else None
    return render_template("instrument.html", page="instruments", inst=inst, price_rows=price_rows,
                           price_count=price_count, bond=bond, asset_classes=ASSET_CLASSES,
                           providers=prices.PROVIDERS.values(), currencies=DISPLAY_CURRENCIES,
                           bond_series=bonds.SERIES)


@bp.get("/sql")
def sql_page():
    return render_template("sql.html", page="sql")


@bp.app_template_filter("num")
def num_filter(value, digits=2):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    s = f"{value:,.{digits}f}".replace(",", " ")
    return s


@bp.app_template_filter("urlencode_page")
def urlencode_page(args, page):
    from urllib.parse import urlencode

    return urlencode({**{k: v for k, v in args.items() if k != "page"}, "page": page})
