# Strategy definition

Validated 2026-08 in the investments repo (`.temp/mf_hc_backtest`). One
portfolio per quarter, formed at quarter_end + 50 days (13F deadline + buffer).

## Selection funnel

1. **HC conviction set.** For each tracked manager (50 CIKs, three tiers in
   `data/managers/candidate_managers.txt`), detect new positions and
   significant adds from 13F filings (`add_dollar_weight` 0.5% or 1.5× share
   increase). A ticker is HC when any manager's trailing-4-quarter purchase
   cost ≥ 7% of their current portfolio (`hc_alt_weight`, dollar-cost basis —
   price appreciation alone never qualifies). Raised from 5% by the 2026-08
   robustness sweep (`backtest/sweep.py`).
2. **Quant pass** (`lib/screen.py::derive_flags`): debt/EBITDA ≤ 5, interest
   cover ≥ 2, no maturity cliff, clean earnings ≥ 50% of NI, no loss year,
   3y revenue CAGR ≥ −5%, FCF/NI ≥ 0.6 (archetype-conditional), franchise +
   quality gates, depository/ETF hard excludes. Missing data passes through.
3. **Magic formula** (`lib/ranks.py`): universe = Compustat USD names,
   market cap ≥ $50M, latest annual data with 90-day filing lag and 550-day
   max age. Excluded: utilities (gsector 55) and US federally regulated
   depositories only (fic USA + SIC 6020–6029/6035/6036/6712, plus the
   config ticker list). Foreign financials stay in; firms with no
   current-asset split get NWC = 0 (ROC = EBIT / net PP&E).
   - Earnings yield = EBIT / (mkt cap + dltt + dlc + mib − che)
   - Return on capital = EBIT / (max(NWC, 0) + net PP&E)
   - `mf_pct` = percentile of summed ranks (0 = best)
   Keep candidates with `mf_pct` ≤ 0.50; select the best 10.
4. **Macro gate** (`lib/macro.py`): when S&P 500 trailing PE > 20, block any
   selection with market cap > 5% of US nominal GDP. Blocked slots are not
   backfilled.

**Position sizing**: equal weight, capped at 20% of the quarter's
contribution per ticker (`sizing.max_weight`); with fewer than 5 names the
remainder stays in cash and is deployed in later, fuller quarters.
Backtested ~0.1pt below uncapped full-period — adopted to remove
single-name tail risk (e.g. 2021Q2 had exactly one qualifier). The cap is
baked into `backtest/run_windows.py` (SPY benchmark exempt).

Full rotation each quarter (no carry — tested and rejected:
−0.4pt full-period, −9pt in 2024–2026H1).

## Backtest evidence (DCA $1k/month, 2015-01 → 2026-05, yfinance prices)

Production rules (TOP10: HC ≥ 7%, quant pass, `mf_pct` ≤ 0.50, best 10),
set by the 2026-08 robustness sweep over 120 variants (`backtest/sweep.py`,
`backtest/outputs/sweep.csv`). Old rules (TOP7: HC ≥ 5%, ≤ 0.40, best 7)
shown for comparison.

Numbers below are with stock-split-adjusted purchase detection
(`lib/signals.py`, fixed 2026-08 — raw QoQ share deltas had misread splits
like CVNA 5:1 as massive purchases) and include the production 20% sizing
cap (uncapped equal weight runs ~0.1pt higher full-period).

| Window | SPY | TOP7 (old) | TOP10 (production) | TOP10 ex-MU |
|---|---|---|---|---|
| 2015–2017 | 16.1% | 22.0% | 19.9% | 19.9% |
| 2018–2020 | 19.4% | 23.5% | 31.5% | 31.1% |
| 2021–2023 | 10.7% | 12.0% | 14.5% | 14.6% |
| 2024–2026H1 | 23.1% | 28.0% | 31.0% | 31.0% |
| Full 2015–2026 | 15.9% | 19.6% | 21.5% | 18.7% |
| Full 2018–2026 | 17.0% | 25.9% | 29.7% | 23.8% |

Why TOP10 over TOP7: TOP7's full-period edge collapsed to ~0 with MU
excluded (~16% vs SPY 15.9%) and to 14.0% with its top-2 contributors
(MU, AAPL) excluded from selection. TOP10 keeps a ~3pt full-period edge
ex-MU, 16.2% with its top-2 contributors (MU, NVDA) excluded, beats SPY
in every 3-year window with or without MU, and had no cash months.
Tighter MF cutoffs (0.20) were pure MU exposure — they lose to SPY
without it. The hc ≥ 7% / top-10 cluster dominated broadly across the
sweep grid (rank 1/120 on the split-fixed data; old TOP7 rules rank
57/120), not as a lone spike.

Caveats: parameters chosen on the same ~11-year sample they're evaluated
on (sweep-selection bias; robustness metrics mitigate but don't remove
it); yfinance drops some delisted tickers; universe percentiles depend on
the financials-inclusion policy (all-financials-excluded variant
backtested ~1pt higher full-period but blanket-rejects names like KSPI).
