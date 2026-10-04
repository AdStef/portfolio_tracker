import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, detect_types=0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA.read_text())
        conn.execute("INSERT OR IGNORE INTO app_state(key, value) VALUES ('data_version', '0')")
    conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value) -> None:
    conn.execute(
        "INSERT INTO app_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def data_version(conn) -> int:
    return int(get_state(conn, "data_version", "0"))


def bump_version(conn) -> int:
    """Call after any write that changes calculation inputs, so the dashboard knows its JSON is stale."""
    conn.execute("UPDATE app_state SET value = CAST(value AS INTEGER) + 1 WHERE key = 'data_version'")
    return data_version(conn)
