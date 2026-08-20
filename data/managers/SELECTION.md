# How the tracked managers were selected

Record of how the CIKs in `candidate_managers.txt` were chosen. Condensed from the audit trail in the investments repo (`US/superinvestors/manager-selection/`, archived 2026-08-19); the reproducible scripts and full scorecard remain there — this file is the summary of record for the standalone pipeline.

The list has three sections, built by three different methods at different times. `lib/managers.py` loads **all three** by default (tiers `Elite`, `BacktestElite`, `PersistenceSelected`); `include_persistence=False` drops section 3. In total ~52 CIKs covering ~50 distinct managers (two managers file under two CIKs each: Terry Smith, Josh Tarasoff).

## Section 1 — Existing tracked investors (14 CIKs, tier `Elite`)

Hand-picked, reputation-based. Well-known concentrated value investors already followed before any quantitative work: Dorsey, Smith, Akre, Klarman, McLemore, Pabrai, Vinall, Tarasoff, Li Lu, Ackman, Sosin, Burry. No formula; kept in full through every revision. This is the only judgment-based section.

## Section 2 — Elite 13F managers, 2013–2017 IRR screen (15 CIKs, tier `BacktestElite`)

A backtest-era screen over 13F filers ranked by implied IRR over 2013Q1–2017Q4, then filtered to the **concentrated, low-churn cohort**:

- Average positions < 20
- Turnover < 15%

The retained table (IRR, TWR, streak, AUM, concentration) is embedded in `candidate_managers.txt`. Includes institutional allocators surfaced by the screen rather than by reputation (Folketrygdfondet, Investor AB, Bain Capital, Silchester, several venture/PE filers). Selection window predates the strategy's backtest start, but the screen itself was not run out-of-sample — treat the 2013–2017 IRRs as descriptive, not predictive.

## Section 3 — Persistence-selected managers (23 CIKs, tier `PersistenceSelected`)

The reproducible, quantitative tier (2026-07 run). Method, implemented in `manager-selection/identify-managers/` (5-script chain):

1. **Filings-implied prices.** No external price feed: a CUSIP-quarter price is the median implied price across all 13F filers holding it (≥2 filers required), from the full SEC bulk 13F panel (2013Q1–2026Q1, 13,127 managers).
2. **Retained-position revaluation returns.** Each manager's quarterly return is computed on the positions they held through the quarter — measuring what their *holdings* did, not their trading.
3. **Benchmark.** Cap-weighted top-500 CUSIPs (an S&P 500 proxy from the same data).
4. **Persistence metrics.** Per manager: information ratio, CAGR, alpha, max drawdown — each also computed separately on the first and second half of the manager's history (split-sample).
5. **Composite score** = 0.5·z(IR) + 0.3·z(CAGR) + 0.2·z(−max drawdown), ranked over the 4,899 managers passing the base filter.

Base filter: ≥20 quarters of history, median AUM ≥ $100M, 5–500 median positions. The key validity check: split-sample IR Spearman ρ = 0.410 across the filtered universe — first-half skill predicts second-half skill, which is the empirical justification for selecting on past returns at all.

Section 3 membership then applied **tighter manual thresholds** on the scorecard: CAGR > 15% in *both* halves, IR positive in *both* halves, alpha > 5%. The 23 survivors (Newbrook, Whale Rock, EMS, Hitchwood, Slate Path, AltaRock, Lone Pine, Appaloosa, SRS, 3G, …) were pasted with their metrics into the txt. CAS Investment Partners appears in both sections 1 and 3 (dedup handled by the loader keying on CIK).

## Known caveats (inherited from the source pipeline)

- Retained-position returns **understate active traders** — a manager who flips positions well looks mediocre; the method favors buy-and-hold styles, which is aligned with how the strategy consumes the signal.
- 13F holdings carry **no dividends** (~2ppt/yr short of total return) and no short positions, options are excluded.
- No CUSIP continuity across corporate actions; quarterly |log-return| capped at 1.6 to suppress data errors.
- The top of the raw scorecard is dominated by small momentum shops (EAM, Lisanti); the manual thresholds and the strategy's dollar-cost conviction filter are what keep the tracked list value-flavored, not the composite score alone.
- Sections 1 and 2 have **no out-of-sample validation**; section 3's split-sample test is in-method but on the same data source.

## Maintenance

`candidate_managers.txt` is the live artifact; the investments repo keeps a copy that must be updated in lockstep (both copies verified identical 2026-08-20). To refresh section 3, re-run `identify-managers/run_all.sh` (pointed at this repo's 13F data), review scorecard deltas, and edit the txt by hand — additions are deliberate, not automatic.

Note: the header comment inside `candidate_managers.txt` ("default reads sections 1+2 only") describes the *old* investments-repo loader and is stale for this repo — `lib/managers.py` here loads all three sections by default.
