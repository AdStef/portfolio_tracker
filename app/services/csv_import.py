"""Two-step CSV import: preview (parse + validate + duplicate check, nothing written) then commit."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from pathlib import Path

from app import db
from app.services import transactions
from app.services.importers import IMPORTERS

TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("cannot decode file")


def _evaluate(conn, text: str, profile: str, account_id: int | None, *, commit: bool):
    importer = IMPORTERS.get(profile)
    if importer is None:
        raise ValueError(f"unknown import profile {profile!r}")
    results = []
    seen: Counter = Counter()
    for parsed in importer.parse(text):
        item = {"line": parsed.line, "data": parsed.data, "status": "ok", "errors": []}
        results.append(item)
        if parsed.error:
            item.update(status="error", errors=[parsed.error])
            continue
        data = dict(parsed.data)
        if account_id:
            data["account_id"] = account_id
        try:
            row = transactions.normalize(conn, data, create_instruments=commit)
        except transactions.ValidationError as exc:
            item.update(status="error", errors=exc.errors)
            continue
        base = transactions.base_hash(row)
        key = f"{base}#{seen[base]}"
        seen[base] += 1
        item["row"] = row
        item["hash"] = key
        if conn.execute("SELECT 1 FROM txn WHERE dedupe_hash = ?", (key,)).fetchone():
            item["status"] = "duplicate"
        elif row.get("_new_instrument"):
            item["new_instrument"] = row["_new_instrument"]["symbol"]
    return results


def preview(conn, import_dir: Path, raw: bytes, filename: str, profile: str, account_id: int | None) -> dict:
    text = _decode(raw)
    token = uuid.uuid4().hex
    import_dir.mkdir(parents=True, exist_ok=True)
    (import_dir / f"{token}.csv").write_text(text, encoding="utf-8")
    (import_dir / f"{token}.name").write_text(filename or "upload.csv", encoding="utf-8")
    results = _evaluate(conn, text, profile, account_id, commit=False)
    conn.rollback()
    return {
        "token": token,
        "summary": dict(Counter(r["status"] for r in results)),
        "new_instruments": sorted({r["new_instrument"] for r in results if r.get("new_instrument")}),
        "rows": [_public(r) for r in results],
    }


def commit(conn, import_dir: Path, token: str, profile: str, account_id: int | None) -> dict:
    if not TOKEN_RE.match(token or ""):
        raise ValueError("invalid token")
    path = import_dir / f"{token}.csv"
    if not path.exists():
        raise ValueError("upload expired, please upload the file again")
    filename = (import_dir / f"{token}.name").read_text(encoding="utf-8")
    try:
        results = _evaluate(conn, path.read_text(encoding="utf-8"), profile, account_id, commit=True)
        ok = [r for r in results if r["status"] == "ok"]
        cur = conn.execute(
            "INSERT INTO import_batch(filename, profile, imported_at, row_count) VALUES (?, ?, ?, ?)",
            (filename, profile, db.now_iso(), len(ok)),
        )
        batch_id = cur.lastrowid
        for r in ok:
            transactions.insert(conn, r["row"], dedupe_hash=r["hash"], batch_id=batch_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"batch_id": batch_id, "imported": len(ok), "summary": dict(Counter(r["status"] for r in results))}


def undo(conn, batch_id: int) -> int:
    n = conn.execute("DELETE FROM txn WHERE import_batch_id = ?", (batch_id,)).rowcount
    conn.execute("DELETE FROM import_batch WHERE id = ?", (batch_id,))
    db.bump_version(conn)
    conn.commit()
    return n


def _public(r: dict) -> dict:
    out = {k: r[k] for k in ("line", "status", "errors", "data")}
    if r.get("new_instrument"):
        out["new_instrument"] = r["new_instrument"]
    if "row" in r:
        out["cash_amount"] = r["row"]["cash_amount"]
        out["cash_currency"] = r["row"]["cash_currency"]
    return out
