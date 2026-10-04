# TODO

## Data & valuation
- [ ] **Price providers**: implement concrete sources in `app/services/prices/` (e.g. Yahoo, Stooq) and link each
      instrument to one (`price_source` + `source_symbol`, already pre-filled like `XTB.WA`, `IWDA.AS`, `EUNA.DE`).
- [ ] **FX rates**: give `EURPLN` and `USDPLN` a source. `USDPLN` has no data yet, so the USD display currency
      falls back to PLN.
- [ ] **PPK unit price** via API / web crawl (manual entry or "total holding value" until then).
- [ ] **Bond parameters**: enter first-period rate, margin and fee for every held series (EDO-120634, EDO-200634,
      TOS-300927); valued at nominal 100 until then.
- [ ] **CPI data**: fill the CPI table (GUS y/y), later fetch it automatically.
- [ ] Floating-rate bonds (ROR/DOR) need the NBP reference rate; for now only via manual `period_rates`.
- [ ] Decide whether PPK net value should also deduct state contributions on early withdrawal
      (`PPK_STATE_LOSS` in `app/services/tax.py`, currently 0).
- [ ] Missing price files for `WSE:ETFBM40TR`, `WSE:ETFBS80TR`, `EUNA:DE` (valued at last trade price).

## Import
- [ ] Broker CSV formats (XTB first) as new `Importer` subclasses in `app/services/importers/`.

## Recalculation
- [ ] **History recalculation option**. Today every *Recalculate* replays the full history from the first
      transaction, so it is always correct but always does the full work. Plan:
      - make the normal recalculation incremental: keep the saved history and only recompute from the earliest
        date touched since the last run (track the minimum changed transaction/price date in `app_state`);
      - add an explicit **"Recalculate full history"** button for when something long ago was changed
        (edited old transaction, back-filled prices, changed bond parameters/CPI).

## UI
- [ ] **Chart animations**: enable Chart.js animations (currently `animation: false` in
      `app/static/js/dashboard.js`) for initial draw and range/scope changes; respect `prefers-reduced-motion`.
- [ ] **CSS margins**:
      - panels in `.grid_2` get both the grid `gap` and their own `margin-bottom` → uneven vertical spacing;
      - topbar metric cards are not vertically aligned (the "Netto" card with a two-line subtitle sits higher);
      - sidebar is `100vh` + `position: fixed`, so the settings block looks detached on long pages;
      - form rows on the transaction form leave orphaned fields (e.g. "Value in PLN" alone on a row);
      - check spacing on narrow screens (< 800px).

## Housekeeping
- [ ] `docker compose up -d` fails with `unknown shorthand flag: 'd'` → Compose plugin missing
      (`sudo pacman -S docker-compose`, or use `docker-compose`).
- [ ] Remove the old `assets/` folder (copied into `app/static/`).
