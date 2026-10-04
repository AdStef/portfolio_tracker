-- Source of truth. Everything derived (valuations, P/L, history) lives in data/snapshots/*.json.

CREATE TABLE IF NOT EXISTS person (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    color       TEXT
);

CREATE TABLE IF NOT EXISTS account (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES person(id) ON DELETE RESTRICT,
    name        TEXT NOT NULL,
    broker      TEXT,
    kind        TEXT NOT NULL DEFAULT 'REGULAR',   -- REGULAR | BONDS | IKE | IKZE | PPK
    currency    TEXT NOT NULL DEFAULT 'PLN',       -- default cash currency for new transactions
    archived    INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    UNIQUE (person_id, name)
);

CREATE TABLE IF NOT EXISTS instrument (
    id             INTEGER PRIMARY KEY,
    symbol         TEXT NOT NULL UNIQUE,           -- internal symbol, e.g. WSE:XTB, AMS:IWDA, EDO-100134, EURPLN
    name           TEXT,
    asset_class    TEXT NOT NULL DEFAULT 'OTHER',  -- see app.constants.ASSET_CLASSES
    currency       TEXT NOT NULL DEFAULT 'PLN',    -- quote currency
    price_source   TEXT NOT NULL DEFAULT 'manual', -- key in the price-provider registry
    source_symbol  TEXT,                           -- symbol understood by the provider, e.g. XTB.WA
    source_config  TEXT,                           -- provider-specific JSON (bond parameters, URLs, ...)
    note           TEXT
);

CREATE TABLE IF NOT EXISTS import_batch (
    id           INTEGER PRIMARY KEY,
    filename     TEXT,
    profile      TEXT NOT NULL,
    imported_at  TEXT NOT NULL,
    row_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS txn (
    id                INTEGER PRIMARY KEY,
    account_id        INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    date              TEXT NOT NULL,               -- YYYY-MM-DD
    type              TEXT NOT NULL,               -- see app.constants.TXN_TYPES
    instrument_id     INTEGER REFERENCES instrument(id) ON DELETE RESTRICT,
    quantity          REAL,
    price             REAL,                        -- in instrument currency
    fee               REAL NOT NULL DEFAULT 0,     -- in cash currency, already included in cash_amount
    tax               REAL NOT NULL DEFAULT 0,     -- in cash currency, already included in cash_amount
    cash_amount       REAL NOT NULL DEFAULT 0,     -- signed effect on account cash
    cash_currency     TEXT NOT NULL,
    amount_pln        REAL,                        -- |cash leg| in PLN at trade time; NULL = use stored FX rate
    counter_amount    REAL,                        -- FX_EXCHANGE only: signed amount of the other currency
    counter_currency  TEXT,
    note              TEXT,
    import_batch_id   INTEGER REFERENCES import_batch(id) ON DELETE SET NULL,
    dedupe_hash       TEXT UNIQUE,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_account_date ON txn(account_id, date);
CREATE INDEX IF NOT EXISTS idx_txn_instrument ON txn(instrument_id);

-- Daily closes for securities AND FX pairs (FX pairs are instruments with asset_class 'FX', e.g. EURPLN).
CREATE TABLE IF NOT EXISTS price (
    instrument_id  INTEGER NOT NULL REFERENCES instrument(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,
    close          REAL NOT NULL,
    source         TEXT,
    PRIMARY KEY (instrument_id, date)
);

-- Polish CPI, year-over-year % as published by GUS (e.g. 4.9 means 4.9%). Used for EDO/COI/ROS/ROD bonds.
CREATE TABLE IF NOT EXISTS cpi (
    month  TEXT PRIMARY KEY,                       -- YYYY-MM
    yoy    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
