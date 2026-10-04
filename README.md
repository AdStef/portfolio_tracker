# portfolio_tracker
Simple self-hosted webapp for tracking investment portfolios of several people, each with several accounts
(regular brokerage, IKE, IKZE, PPK, treasury bonds).

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python run.py                 # http://127.0.0.1:5000, data in ./data
.venv/bin/python -m pytest              # tests
```

or with Docker: `docker compose up -d --build` → http://localhost:8000 (data in `./data`).
If that fails with `unknown shorthand flag: 'd' in -d`, the Compose plugin is missing: install it
(`sudo pacman -S docker-compose` on Arch/CachyOS) or use the standalone `docker-compose up -d --build`.

### One-time migration of the old Google Sheet

```bash
.venv/bin/python -m scripts.import_legacy --person "Adam"
# docker: docker compose run --rm portfolio python -m scripts.import_legacy --person "Adam" \
#           --csv "/legacy/Portfolio_tracker - Transakcje.csv" --eod-dir /legacy
```

## How it works

```
SQLite (data/portfolio.db)  ──Recalculate / Refresh prices──▶  engine  ──▶  data/snapshots/*.json  ──▶  dashboard
 people, accounts, instruments,                                  FIFO lots, cash per currency,         dashboard.json (totals,
 transactions, prices, CPI                                       FX, bonds, exit tax, XIRR, history    positions), history.json
```

* The database is the source of truth; every write bumps `data_version`.
* The dashboard only reads the JSON snapshot. If `data_version` changed since it was written, a
  "data changed" badge suggests pressing **Recalculate**. **Refresh prices** downloads missing prices and recalculates.
* All amounts are computed in PLN; the PLN/EUR/USD switch converts in the browser using stored FX rates
  (FX pairs are instruments `EURPLN`, `USDPLN` with asset class `FX`).

| Path | Purpose |
|---|---|
| `app/services/engine.py` | calculation engine (pure function) |
| `app/services/tax.py` | net value rules: Belka 19% (regular, IKE), IKZE 10% flat, PPK −30% employer part + Belka |
| `app/services/bonds.py` | EDO/COI/TOS/ROS/ROD/OTS valuation from series rules + CPI (Instruments page) |
| `app/services/prices/` | price-provider registry – link an instrument to a source via `price_source`/`source_symbol` |
| `app/services/importers/` | CSV import profiles (`native` now; broker formats plug in here) |
| `app/services/recalc.py` | DB → engine → snapshot, price refresh |
| `app/i18n.py` | PL/EN strings |

### Adding a price source
Subclass `PriceProvider` in `app/services/prices/`, implement `fetch(instrument, since, until)` returning
`PricePoint`s, and `register()` it. It then appears in the instrument's *Price source* dropdown.

### Adding a broker CSV format
Subclass `Importer` in `app/services/importers/`, map the broker's rows to the keys accepted by
`transactions.normalize()` (see `native.py`), and add it to `IMPORTERS`.
