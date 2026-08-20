# 13f-clone — HC ∩ Magic Formula strategy

Self-contained quarterly stock-selection pipeline. Each quarter it builds the
high-conviction (HC) set from tracked superinvestors' 13F filings, filters by
a fundamentals quant screen and a Greenblatt magic-formula percentile, and
outputs the top-10 portfolio plus a funnel report explaining every name's fate.

## Quarterly run

```
C:\envs\.basic_venv\Scripts\python.exe run_quarter.py 2026Q2
```

Outputs to `quarters/2026Q2/`:
- `03_portfolio.txt` — final tickers
- `04_funnel.md` — every HC name with the reason it was selected or cut
- `01_screen.csv`, `02_ranks.parquet` — intermediates

`--no-refresh` skips network refresh (uses local data as-is).

## Strategy (see STRATEGY.md)

1. **HC**: any tracked manager's trailing-6-quarter purchases ≥ 10% of their
   portfolio (SEC 13F, 50 CIKs in `data/managers/candidate_managers.txt`).
2. **Quant pass**: leverage, interest cover, clean earnings, revenue,
   cash conversion, quality-gate flags (`lib/screen.py`).
3. **Magic formula**: EBIT/EV + EBIT/(NWC + net PP&E) combined percentile vs
   the global universe (USD, ≥$50M cap; utilities and US federally regulated
   depositories excluded; foreign financials like KSPI stay in). Ranks only
   — no hard percentile filter — then take the best 7.
4. **Price cap**: skip names up more than +100% since the quarter the
   managers first bought them. A discipline rule, not an edge (costs
   ~0.6pt/yr); disable with `price_cap.max_runup: null`.
5. **Macro gate**: when S&P PE > 20, block names with market cap > 5% of GDP.
6. **Sizing**: equal weight, max 20% per ticker; remainder to cash.

Backtest (2015–mid-2026, DCA $1k/month, 20% cap applied): 22.1% XIRR vs
SPY 15.9%, beating SPY in all four 3-year windows. On a 2024–2026 holdout
the rules never saw, +9.7pt vs SPY. Run `backtest/run_windows.py`;
parameter sweep: `backtest/sweep.py`; full variant log:
`backtest/VARIANTS.md`.

## Data freshness (every run)

- **13F**: bulk SEC data appended automatically; if the bulk quarter is not
  yet published, individual EDGAR 13F-HR filings are fetched and used when
  ≥ 75% of tracked managers have filed (stamped PROVISIONAL).
- **Fundamentals**: HC candidates whose Compustat row is > 6 months old are
  checked against SEC companyfacts; if EDGAR has a newer fiscal year, EBIT/EV
  and ROC are recomputed and the name re-located in the rank distribution.
  IFRS/20-F filers without US-GAAP tags fall back to Compustat.
- **Macro**: GDP from FRED (key at `C:/key-variables/key-variables.yaml`),
  S&P PE scraped from multpl.com.
- **Compustat panel**: WRDS-sourced, cannot auto-refresh — see
  `data/compustat/REFRESH.md`; check age with
  `refresh/compustat_staleness.py [QUARTER]`.

## Layout

- `lib/` — pipeline modules (config-driven via `config.yaml`); `ranks.py` is
  the magic-formula rank builder.
- `data/` — 13F slim parquet (tracked CIKs only, append-only with state.json
  guard), Compustat staging parquets + local duckdb, macro parquets, caches.
- `refresh/` — dataset refreshers. `build_compustat_db.py` must be re-run if
  the repo moves on disk (duckdb views bake absolute paths).
- `backtest/` — DCA/XIRR window backtest with seeded screen-history and
  price caches (`build_screen_history.py` / `fetch_prices.py` to rebuild).

## Requirements

Python venv at `C:\envs\.basic_venv` (pandas, pyarrow, duckdb, pyyaml,
requests, yfinance, scipy).
