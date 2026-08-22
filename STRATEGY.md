# HC ∩ Magic Formula — Strategy Description

A quarterly, rules-based US-listed equity strategy that buys what proven value investors are buying, but only when the business is financially sound and the price is attractive relative to the quality of the business. One portfolio is formed each quarter; it is fully rotated the next quarter.

This document describes every rule in the strategy, why each rule exists, and the backtest evidence behind the current parameters. Nothing is discretionary: given the same inputs, the pipeline always produces the same portfolio.

## The idea in one paragraph

Roughly 50 investment managers with strong long-term records ("tracked managers") must disclose their US equity holdings every quarter in SEC 13F filings. When one of them puts a large share of their portfolio into a single stock, that is a costly, verifiable signal of conviction. The strategy starts from those high-conviction purchases, removes companies whose financial statements show fragility, ranks the survivors by Joel Greenblatt's "magic formula" (cheap price for a high-return business), and buys the best seven, equally weighted. Two overlays temper the entry: a cap on chasing stocks that have already doubled, and a block on mega-caps when the overall market is expensive.

## Step 1 — The high-conviction (HC) set

For each tracked manager, quarterly 13F filings are converted into purchase actions (new positions and significant additions). A stock enters the HC set when a manager's **cumulative purchase cost over the trailing 6 quarters reaches at least 10% of their current portfolio value**.

Two design points matter:

- **Dollar-cost basis.** The 10% is measured on what the manager actually spent, not on what the position is now worth. A position that grew to 10% through price appreciation alone never qualifies — only deliberate buying does.
- **A 6-quarter window.** Large investors build positions over several quarters. A single-quarter test misses slow accumulation; the 18-month window captures the full campaign. The 10% threshold and the 6-quarter window were set jointly by a 640-variant parameter sweep (see "Evidence" below) — a longer window at a lower threshold simply dilutes the portfolio.

## Step 2 — The quant screen

Every HC candidate must pass eleven accounting-based tests, computed from its most recent annual financial statements. The screen's purpose is not to find winners — the managers do that — but to veto situations where the downside is structural: too much debt, profits that are not real, or a business that earns poor returns on the capital it employs.

The tests are grouped by the question they answer. **Missing data passes**: a company is never rejected because a data field is unavailable, only because a computed metric fails its test.

### Can the company survive? (solvency)

| Test | Rule | What it measures / why it is in |
|---|---|---|
| Leverage | Net debt / EBITDA ≤ 5 | Total indebtedness against cash earnings. Above ~5×, equity holders are effectively junior to a refinancing schedule. |
| Interest cover | EBIT / interest expense ≥ 2 | Whether operating profit comfortably services the debt. Catches firms with cheap-looking debt loads but thin coverage. |
| Maturity cliff | Fails only if debt due within 2 years > 20% of market cap **and** interest cover < 4 | A large near-term repayment is only dangerous when coverage is also weak; the combined test avoids penalising firms that can obviously refinance. |

### Are the profits real? (earnings quality)

| Test | Rule | What it measures / why it is in |
|---|---|---|
| Clean earnings | Core net income ≥ 50% of reported net income | Core = reported income minus special items, non-operating income, and extraordinary items. Rejects profits manufactured by one-off gains. |
| No loss year | Core net income ≥ 0 (waived for cyclical industries) | A currently loss-making business cannot be valued on its earnings. Cyclicals are exempt because a trough-year loss is expected, not disqualifying. |
| Cash conversion | Asset-light firms: free cash flow ≥ 60% of net income (3-yr). Industrial firms fail only when FCF/NI < 40% **with no heavy capex to explain it** | Profits should become cash. For a software or brand business there is no excuse for low conversion; for a factory-heavy business, capex is a legitimate reason, so only the unexplained gap is penalised. |

### Does the business earn its keep? (quality)

Each company is first classified into an archetype from its balance-sheet mix and industry code — tangible-operating (factories, inventory), asset-light (intangibles, software, brands), cyclical (energy, mining, semiconductors, shipping), plus banks, REITs, utilities, and a residual bucket — because a single profitability yardstick misleads across these types.

| Test | Rule | What it measures / why it is in |
|---|---|---|
| Quality gate | Tangible-operating: 3-yr pre-tax return on invested capital ≥ 15%. Asset-light: return on capital excluding goodwill ≥ 20% **and** gross margin ≥ 40% | The core test of business quality. The asset-light version strips goodwill so a company cannot hide a mediocre core business behind acquisitions, and requires the gross margin of a genuine franchise. In ablation testing this is the single most valuable filter in the screen (removing it costs ~1.7 points of annual return). |
| Franchise test | Cyclicals: pre-tax ROIC ≥ 8% (3-yr average or latest). Unclassified firms: ≥ 10% | A gentler bar for company types where the 15% test would measure the position in the cycle rather than the quality of the business. Deliberately loose: tightening it was tested and rejected because it blocks exactly the trough-recovery entries the strategy exists to find. |

### Hygiene

| Test | Rule | Why |
|---|---|---|
| Revenue trend | 3-yr revenue CAGR ≥ −5% | Excludes structurally melting businesses; mild declines (cyclical or FX-driven) still pass. |
| Depository exclude | No US regulated banks | Bank balance sheets cannot be assessed with these metrics, and deposit-funded leverage is a different risk class. Foreign non-bank financials remain eligible. |
| ETF exclude | No funds/trusts | The strategy selects businesses, not wrappers. |

Roughly 39% of HC candidates pass the full screen. The filters deliberately overlap — an over-leveraged company usually fails coverage and quality too — so no single test is load-bearing, but removing the whole screen costs ~1.1 points of annual return and visibly degrades the 2021–23 bear market window. A full ablation study (each filter removed one at a time, and all 16 combinations of the four groups) is in `backtest/VARIANTS.md`.

## Step 3 — Magic-formula ranking

Survivors are ranked by Greenblatt's two factors, computed against the **entire universe** of US-listed companies (USD reporting, market cap ≥ $50M, financial data no older than 550 days, applied with a 90-day reporting lag to avoid look-ahead):

- **Earnings yield** = EBIT / enterprise value — how much operating profit you buy per dollar, debt included. Cheapness.
- **Return on capital** = EBIT / (net working capital + net fixed assets) — what the business earns on the capital actually tied up in operations. Quality.

Each company's two ranks are summed and converted to a percentile. The percentile is used **only to order the candidates** — there is no hard cut-off. Ranking against the full market rather than within the candidate list means "cheap" always has the same meaning regardless of how many candidates a quarter produces.

## Step 4 — Price-runup cap

Any candidate whose share price has risen **more than 100%** since the end of the quarter in which the earliest tracked manager began buying is dropped, and the next-ranked name takes its place.

This rule is disclosed as what it is: a behavioural constraint, not a return enhancer. Every threshold tested *cost* performance (the +100% level costs ~0.6 points per year). It exists because systematically buying a stock that has already doubled is the hardest instruction in the strategy to follow by hand, and a stated rule is safer than ad-hoc skipping. +100% is the knee of the cost curve — tighter caps cost several times more.

## Step 5 — Final selection and sizing

- Take the **top 7** names by magic-formula rank.
- **Macro mega-cap gate:** when the S&P 500 trailing P/E exceeds 20, any selection whose market cap exceeds 5% of US GDP is removed and **not** replaced. When the index is expensive, its largest names carry the most de-rating risk; leaving the slot empty rather than backfilling keeps the gate from forcing weaker names into the book.
- **Equal weight, 20% maximum per position.** With fewer than five names, the excess stays in cash and is deployed in later, fuller quarters.
- **Full quarterly rotation.** Carrying positions between quarters was tested and rejected (−0.4 points full-period, −9 points in 2024–26).

In practice the portfolio holds about 5 names per quarter on average; the screen, not the top-7 cut, is usually the binding constraint.

## Evidence

Backtest: $1,000 invested monthly, January 2015 – May 2026, prices from Yahoo Finance, positions formed 50 days after each quarter-end (the 13F filing deadline plus a buffer). Returns are money-weighted (XIRR), the correct measure for a strategy that receives contributions over time.

| Window | S&P 500 (SPY) | Strategy |
|---|---|---|
| 2015–2017 | 16.1% | 24.3% |
| 2018–2020 | 19.4% | 31.9% |
| 2021–2023 | 10.7% | 19.9% |
| 2024–2026H1 | 23.1% | 32.2% |
| **Full period** | **15.9%** | **22.1%** |

The strategy beats the index in all four 3-year windows, with one month of forced cash in eleven years.

**Parameter selection and out-of-sample check.** The current parameters were chosen by a 640-variant sweep scored on robustness (performance with the two biggest winners removed, plus worst-window performance) rather than raw return. As a check against overfitting, the sweep was re-run using only 2015–2023 data: the chosen parameters ranked 2nd of 640 on that training period alone, and returned **32.8% vs SPY's 23.1%** on the untouched 2024–2026 holdout.

## Honest limitations

- **Survivorship pressure.** The price source drops some delisted tickers, which biases backtest returns upward by an unknown but nonzero amount.
- **The holdout is not fully clean.** The parameter grid was widened after earlier full-sample results had flagged the winning region, so the out-of-sample check is best read as "not contradicted" rather than "validated." The holdout period was also one in which most variants beat the index.
- **Concentration.** Five to seven positions means single-name outcomes dominate any given year. The robustness scoring and the 20% cap mitigate but do not remove this.
- **Signal lag.** 13F data is up to 135 days old at formation. The strategy is built on the persistence of manager conviction, not on speed.
- **Screen power.** With ~5 names per quarter over 11 years, backtests cannot statistically distinguish nearby screen designs; the screen is retained on aggregate evidence and economic rationale, not per-filter proof.

## Supplementary output: the watchlist

Alongside each quarter's portfolio, the pipeline produces a research watchlist that is **not part of the strategy**. It starts from names tracked managers bought at 1–10% of their book — below the conviction threshold — keeps only those that pass the full quant screen and rank in the better half of the magic-formula universe, and then an AI reviewer (Claude) selects and ranks a handful in the order they merit further work as long-term investments. The mechanical filter is reproducible; the final selection and ranking are explicitly subjective, are labelled as such in each `05_watchlist.md`, and no capital is allocated to them by rule. The watchlist exists to surface accumulating conviction early (a manager at 8% this quarter is often at 12% next quarter), not to add discretionary positions.

Full variant-by-variant experiment history, including every rejected alternative: `backtest/VARIANTS.md`.
