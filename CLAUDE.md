# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- Python venv: `C:\envs\.basic_venv` — run everything with `C:\envs\.basic_venv\Scripts\python.exe` (pandas, pyarrow, duckdb, pyyaml, requests, yfinance, scipy).
- API keys / secrets live at `C:\key-variables\key-variables.yaml` (e.g. `api_keys.fred` for the FRED GDP refresh). Never copy values from it into the repo.
- No test suite, linter, or build step. Correctness is checked by running the pipeline and inspecting outputs (`04_funnel.md`, `backtest/outputs/windows.csv`).

## Commands

```
# Quarterly production run (the main entry point)
C:\envs\.basic_venv\Scripts\python.exe run_quarter.py 2026Q2
C:\envs\.basic_venv\Scripts\python.exe run_quarter.py 2026Q2 --no-refresh   # skip network refresh

# Backtest (DCA/XIRR per 3-year window + full period)
C:\envs\.basic_venv\Scripts\python.exe backtest\run_windows.py

# Rebuild backtest caches after a 13F/Compustat refresh (slow)
C:\envs\.basic_venv\Scripts\python.exe backtest\build_screen_history.py
C:\envs\.basic_venv\Scripts\python.exe backtest\fetch_prices.py

# Check Compustat panel age (optionally per-quarter HC staleness)
C:\envs\.basic_venv\Scripts\python.exe refresh\compustat_staleness.py [QUARTER]

# Rebuild duckdb views — REQUIRED whenever the repo moves on disk
# (the duckdb bakes ABSOLUTE staging paths)
C:\envs\.basic_venv\Scripts\python.exe refresh\build_compustat_db.py
```

## What this repo is

Self-contained quarterly stock-selection pipeline (HC ∩ Magic Formula). Each quarter: build the high-conviction (HC) set from 50 tracked superinvestors' 13F filings, apply a fundamentals quant screen, rank by Greenblatt magic-formula percentile against the global Compustat universe, take the top 10, apply a macro mega-cap gate. Full strategy definition and backtest evidence: `STRATEGY.md`; the variant-by-variant experiment log behind the current parameters is `backtest/VARIANTS.md`. Portfolio is fully rotated each quarter (carry was tested and rejected).

## Pipeline architecture

`run_quarter.py` orchestrates; all logic lives in `lib/` modules, all thresholds and paths in `config.yaml` (loaded via `lib/config.py`, the single source of truth — don't hardcode paths or thresholds).

Stage order (outputs to `quarters/{Q}/`: `01_screen.csv`, `02_ranks.parquet`, `03_portfolio.txt`, `04_funnel.md`):

1. **13F freshness** (`ensure_13f`): if the quarter is beyond the bulk parquet's `max_quarter`, try `refresh/refresh_13f.py` (SEC bulk append); if bulk isn't published yet, `refresh/fetch_13f_filings.py` builds a *provisional* sidecar from individual EDGAR 13F-HR filings, used only when manager coverage ≥ 75% (`provisional.min_coverage`). Sidecars live in `data/13f/provisional/` and are NEVER merged into the authoritative parquet.
2. **HC set** (`lib/holdings.py`, `lib/signals.py`, `lib/bands.py`): amendment-deduped equity holdings → purchase actions → `hc_alt_weight` = dollar-cost purchases over the trailing `bands.hc_lookback_qtrs` (6) quarters / current portfolio; HC when ≥ `bands.hc_min_weight` (10%). Dollar-cost basis — price appreciation alone never qualifies a name. Also emits `first_buy_quarter` for the price cap.
3. **Fundamentals patch** (`refresh/refresh_fundamentals.py`): HC candidates whose Compustat row is > `fundamentals.stale_days` old get EBIT/EV and ROC recomputed from EDGAR companyfacts and re-located in the rank distribution. IFRS/20-F filers without US-GAAP tags fall back to Compustat.
4. **Quant screen** (`lib/screen.py::derive_flags`): leverage, interest cover, clean earnings, revenue CAGR, cash conversion, quality gates. Missing data passes through.
5. **Magic formula** (`lib/ranks.py`): percentile of summed EBIT/EV + ROC ranks vs the global universe (USD, ≥$50M cap, 90-day filing lag, 550-day max age). `mf.pctile_cutoff` is `null` — the percentile RANKS only, no hard filter — then take `mf.top_n` (7).
6. **Price-runup cap** (`lib/pricecap.py`): drop candidates up more than `price_cap.max_runup` (+100%) since the end of `first_buy_quarter`. Applied BEFORE the top_n cut (survivors backfill). Behavioural constraint, costs ~0.6pt/yr — see `backtest/VARIANTS.md`.
7. **Macro gate** (`lib/macro.py`): when S&P PE > 20, block names with market cap > 5% of US GDP. Applied AFTER the top_n cut; blocked slots are not backfilled.
8. **Sizing**: equal weight capped at `sizing.max_weight` (20%) per ticker; remainder listed as CASH in `03_portfolio.txt`.

`04_funnel.md` records every HC name with the exact reason it was selected or cut — the primary artifact for verifying a run.

## Data layer

- `data/13f/13f_holdings_slim.parquet` — tracked-CIK-only slim 13F panel, **append-only**, guarded by `13f_holdings_slim.state.json` (max_quarter). A refresh with nothing new makes zero writes.
- `data/compustat/` — WRDS Compustat annual panel as staging parquets (`staging/fyear=YYYY/`) + `compustat.duckdb` holding VIEWS over them. Cannot auto-refresh; manual WRDS export procedure in `data/compustat/REFRESH.md` (~twice a year). Accessed read-only via `lib/data_access.py`.
- `data/macro/` — GDP (FRED) and S&P PE (scraped from multpl.com) parquets, upserted by `refresh/refresh_macro.py`.
- `data/cache/edgar/` — cached companyfacts JSONs.
- `data/managers/candidate_managers.txt` — the 50 tracked CIKs, three tiers; how they were selected: `data/managers/SELECTION.md`.

## Domain rules to preserve

Universe exclusion policy is deliberate operator policy, not an implementation detail: utilities (gsector 55) always excluded; financials excluded ONLY when US-domiciled and federally regulated (SIC 6020–6029/6035/6036/6712 + `hard_excludes.depositories` ticker list) — foreign financials like KSPI stay in. Firms without a current-asset split get NWC = 0. Don't "fix" these without asking.
