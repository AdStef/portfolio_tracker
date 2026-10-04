import io

import pytest

from app import create_app
from app.services.importers.native import TEMPLATE


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


def setup_accounts(c):
    pid = c.post("/api/people", json={"name": "Adam"}).get_json()["id"]
    c.post("/api/accounts", json={"person_id": pid, "name": "XTB PLN", "kind": "REGULAR", "currency": "PLN"})
    c.post("/api/accounts", json={"person_id": pid, "name": "XTB EUR", "kind": "REGULAR", "currency": "EUR"})
    return pid


def test_pages_render(client):
    setup_accounts(client)
    for lang in ("pl", "en"):
        client.set_cookie("lang", lang)
        for url in ("/", "/holdings", "/transactions", "/transactions/new", "/import", "/accounts", "/instruments",
                    "/sql"):
            r = client.get(url)
            assert r.status_code == 200, url


def test_add_transaction_computes_cash_and_creates_instrument(client):
    setup_accounts(client)
    r = client.post("/api/transactions", json={"date": "2024-01-11", "account_id": 1, "type": "BUY",
                                               "symbol": "WSE:XTB", "quantity": "4", "price": "28,34", "fee": "1"})
    assert r.status_code == 201, r.get_json()
    rows = client.get("/api/transactions").get_json()
    assert rows[0]["cash_amount"] == pytest.approx(-114.36)
    assert rows[0]["symbol"] == "WSE:XTB"
    assert client.get(f"/transactions/{rows[0]['id']}/edit").status_code == 200

    bad = client.post("/api/transactions", json={"date": "x", "account_id": 1, "type": "BUY"})
    assert bad.status_code == 400
    assert bad.get_json()["errors"]


def test_import_preview_commit_dedupe_and_undo(client):
    setup_accounts(client)
    data = {"profile": "native", "file": (io.BytesIO(TEMPLATE.encode()), "t.csv")}
    prev = client.post("/api/import/preview", data=data, content_type="multipart/form-data").get_json()
    assert prev["summary"] == {"ok": 4}, prev
    assert prev["new_instruments"] == ["WSE:XTB"]
    res = client.post("/api/import/commit", json={"token": prev["token"], "profile": "native"}).get_json()
    assert res["imported"] == 4

    data = {"profile": "native", "file": (io.BytesIO(TEMPLATE.encode()), "t.csv")}
    again = client.post("/api/import/preview", data=data, content_type="multipart/form-data").get_json()
    assert again["summary"] == {"duplicate": 4}

    assert client.delete(f"/api/import/{res['batch_id']}").get_json()["deleted"] == 4
    assert client.get("/api/transactions").get_json() == []


def test_recalculate_and_stale_flag(client):
    setup_accounts(client)
    assert client.get("/api/dashboard").get_json()["snapshot"] is None
    client.post("/api/transactions", json={"date": "2024-01-10", "account_id": 1, "type": "DEPOSIT", "amount": "1000"})
    assert client.post("/api/recalculate").status_code == 200
    d = client.get("/api/dashboard").get_json()
    assert d["stale"] is False
    assert d["snapshot"]["totals"]["gross"] == 1000
    h = client.get("/api/history?scope=person:1").get_json()
    assert h["series"]["gross"][-1] == 1000

    client.post("/api/transactions", json={"date": "2024-01-11", "account_id": 1, "type": "WITHDRAWAL", "amount": "10"})
    assert client.get("/api/dashboard").get_json()["stale"] is True
    r = client.post("/api/prices/refresh").get_json()  # refresh also recalculates
    assert r["ok"] and client.get("/api/dashboard").get_json()["stale"] is False


def test_manual_price_by_total_value_and_bond_params(client):
    setup_accounts(client)
    client.post("/api/transactions", json={"date": "2024-01-11", "account_id": 1, "type": "BUY", "symbol": "PPK",
                                           "quantity": "200", "price": "1", "amount": "200"})
    r = client.post("/api/instruments/1/prices", json={"date": "2024-02-01", "total_value": "250"})
    assert r.get_json()["close"] == pytest.approx(1.25)

    client.post("/api/transactions", json={"date": "2024-01-10", "account_id": 1, "type": "BUY",
                                           "symbol": "EDO-100134", "quantity": "5", "price": "100"})
    inst = client.get("/api/transactions?instrument_id=2").get_json()[0]
    assert inst["symbol"] == "EDO-100134"
    r = client.put(f"/api/instruments/{inst['instrument_id']}/bond", json={"first_rate": "6,8", "margin": "1.25"})
    assert r.status_code == 200, r.get_json()
    p = client.get(f"/api/instruments/{inst['instrument_id']}/bond-preview?date=2025-01-10").get_json()
    assert p["value"] == pytest.approx(106.8)
    assert client.get(f"/instruments/{inst['instrument_id']}").status_code == 200


def test_sql_is_read_only(client):
    setup_accounts(client)
    ok = client.post("/api/sql", json={"query": "SELECT name FROM person"}).get_json()
    assert ok["rows"] == [["Adam"]]
    bad = client.post("/api/sql", json={"query": "DELETE FROM person"})
    assert bad.status_code == 400
