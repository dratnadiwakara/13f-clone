# Variant log — what was tried, what it returned, what was kept

Record of the 2026-08 parameter investigation that moved production from
`HC ≥ 7% / 4Q / mf_pct ≤ 0.50 / top 10` to
`HC ≥ 10% / 6Q / mf_pct rank-only / top 7 / price cap +100%`.

All figures are XIRR on the standard harness: DCA $1,000/month on the 20th,
equal weight across the active set, never sell, yfinance prices, 20% sizing
cap (`sizing.max_weight`) except where noted. "FULL" = 2015-01 → 2026-05.
SPY on the same schedule: 16.13 / 19.37 / 10.66 / 23.11 / **15.86**.

Reproduce with `backtest/run_windows.py` (single rule set, reads
`config.yaml`) and `backtest/sweep.py` (the grid).

---

## 1. Macro gate — was it doing anything?

The gate (`lib/macro.py`: S&P PE > 20 → block names with cap > 5% of US GDP,
no backfill) was implemented in `run_quarter.py` but **absent from the
backtest** entirely. Added and measured against the then-production TOP10.

| Window | TOP10 | TOP10 + gate | Δ |
|---|---|---|---|
| 2015–2017 | 19.92 | 19.92 | 0.00 |
| 2018–2020 | 31.53 | 31.28 | −0.25 |
| 2021–2023 | 14.47 | 14.05 | −0.42 |
| 2024–2026H1 | 31.00 | 28.08 | −2.92 |
| FULL | 21.54 | 21.70 | +0.16 |

Binds on 6 tickers over 11 years (GOOGL, MSFT, META, AAPL, AMZN, AVGO).
Roughly neutral full-period, real drag recently; DCA reallocates the blocked
money into the remaining names. **Kept** — it is a deliberate risk policy,
and it is now applied in every backtest and every sweep variant.

Note the pre-2017 gap: `sp_pe.parquet` starts 2017-01, so the gate is dormant
for 11 of 49 quarters and the 2015–2017 zero-delta is partly missing data.

## 2. HC lookback length

`hc_alt_weight` summed purchases over a trailing window. Tested k = 1, 2, 3,
4, 5, 6, 8 quarters. k = 4 recomputed from raw data matches the shipped
`hc_alt_weight` to 7e-15, so the other k values are trustworthy by
construction.

At a **fixed 7% threshold**:

| Window | 1q | 2q | 3q | 4q (was prod) | 5q | 6q | 8q |
|---|---|---|---|---|---|---|---|
| 2015–2017 | 17.40 | 18.91 | 19.16 | 19.92 | 18.99 | 18.27 | 19.03 |
| 2018–2020 | 34.34 | 33.76 | 31.91 | 31.53 | 30.22 | 29.40 | 26.65 |
| 2021–2023 | 15.50 | 14.03 | 14.28 | 14.47 | 15.05 | 15.54 | 18.47 |
| 2024–2026H1 | 32.37 | 32.31 | 28.41 | 31.00 | 31.50 | 31.39 | 29.80 |
| FULL | 21.54 | 21.99 | 21.41 | 21.54 | 20.94 | 20.72 | 20.28 |

Two findings. Full-period is flat within ±0.3pt for k ≤ 4 — 1q and 4q land
within 0.003pt of each other (terminal $507,552 vs $507,563) despite holding
87 vs 114 distinct tickers, because the 20% cap concentrates both into the
same compounders. And beyond k = 4 it decays monotonically (21.54 → 20.94 →
20.72 → 20.28), because a longer window sums more purchases, so more names
clear a fixed bar (7.1 → 7.9 → 8.3 names/quarter) and the book dilutes.

**Lookback length alone is close to a free parameter.** It only matters
paired with the threshold.

Holding book size fixed instead of threshold confirms it — matching
production's ~7 names/quarter with a shorter window is strictly worse
(1q/5%: 19.64 FULL; 1q/3%: 18.83; 2q/5%: 20.22).

## 3. Threshold × lookback interact

Raising the threshold with the window inverts the k > 4 decay. 6q at 10%
returns **23.01 FULL** (+1.5pt over the then-production rules) at a
comparable 5.1 names/quarter.

Median robustness score by cell (quant on, from the 640-variant sweep) shows
a clean diagonal — off-diagonal cells are negative:

| hc_min \ lookback | 1q | 2q | 4q | 6q |
|---|---|---|---|---|
| 0.03 | **+0.018** | +0.004 | −0.008 | −0.002 |
| 0.05 | +0.011 | −0.010 | −0.008 | −0.012 |
| 0.07 | −0.019 | +0.003 | −0.057 | −0.060 |
| 0.10 | −0.050 | −0.036 | +0.024 | **+0.037** |

## 4. The 640-variant sweep

`backtest/sweep.py`, extended with a lookback axis and the macro gate:
cutoff {0.2, 0.3, 0.4, 0.5, none} × top_n {5, 7, 10, none} × hc_min {0.03,
0.05, 0.07, 0.10} × lookback {1, 2, 4, 6} × quant {on, off} = 640.

Score = (full-period XIRR with the variant's own top-2 profit contributors
excluded − SPY) + worst 3-year window excess vs SPY. The sweep engine uses
uncapped equal weight, so its levels run ~0.35pt above `run_windows.py`.

Top 6 plus the incumbent:

| cutoff | top_n | hc_min | lookback | FULL | ex-top2 | worst window | names/q | score |
|---|---|---|---|---|---|---|---|---|
| none | 7 | 0.10 | 6q | 22.00 | 17.99 | +7.68 | 5.1 | **0.098** |
| none | 10 | 0.10 | 6q | 21.63 | 17.92 | +7.15 | 5.8 | 0.092 |
| none | none | 0.10 | 6q | 20.86 | 16.23 | +7.07 | 6.4 | 0.074 |
| 0.4 | 10 | 0.10 | 6q | 22.03 | 15.80 | +6.32 | 4.1 | 0.063 |
| 0.5 | 7 | 0.10 | 6q | 22.87 | 17.09 | +4.93 | 4.5 | 0.062 |
| 0.5 | 10 | 0.07 | 4q | 21.89 | 15.81 | +3.71 | 6.8 | 0.037 (old prod, rank 41/640) |

`hc_min = 0.10` takes 27 of the top 50 slots and 6q takes 18 — a plateau,
not a spike. The winner drops the hard `mf_pct` filter entirely, using the
percentile only to order candidates.

Per-window, under the production engine (20% cap, gate on), the finalists:

| Window | SPY | old prod | A: none/7/10%/6q | 0.5/10/10%/6q | 0.5/10/10%/4q |
|---|---|---|---|---|---|
| 2015–2017 | 16.13 | 19.92 | **24.52** | 21.27 | 19.67 |
| 2018–2020 | 19.37 | 31.28 | **31.69** | 30.03 | 30.90 |
| 2021–2023 | 10.66 | 14.05 | 19.90 | 19.73 | 19.01 |
| 2024–2026H1 | 23.11 | 28.08 | **32.61** | 25.21 | 21.04 |
| FULL | 15.86 | 21.70 | 22.70 | 23.26 | 23.20 |
| cash months | 0 | 0 | 1 | 4 | 10 |

Variants B/C/D show marginally higher full-period XIRR but buy it with 4–10
cash months and much weaker recent windows. **A selected.**

## 5. Holdout validation

Re-ran the full 640-variant sweep scoring **only on 2015-01 → 2023-12**, then
evaluated on an untouched 2024-01 → 2026-05 holdout. SPY: train 12.77,
holdout 23.11.

| Variant | Train rank | Train XIRR | Train score | Holdout | Holdout excess |
|---|---|---|---|---|---|
| A — none/7/10%/6q | **2 / 640** | 16.63 | +10.68 | **32.76** | **+9.66** |
| old prod — 0.5/10/7%/4q | 158 / 640 | 17.73 | +5.18 | 27.98 | +4.87 |

Across all 640: Spearman(train score, holdout excess) = 0.169, Pearson 0.303.
Median holdout excess +1.69pt overall, +4.74pt for the top-10 by train score,
−10.55pt for the bottom-10. The score ranks coarsely but avoids disasters.
60% of all variants beat SPY in the holdout.

**Contamination caveat.** The train-side ranking is genuinely blind, but the
grid was widened (adding `hc_min` 0.10 and the 6q lookback) *after*
full-sample runs had flagged that region. The choice of what to search was
informed by data including the holdout. Not a clean out-of-sample test of A
specifically.

## 6. Price-runup cap

Motivated by execution psychology, not by expected return: buying a name
already up 100% since the managers started accumulating is hard to do by
hand, and unplanned discretionary skips are worse than a stated rule.

runup = price(formation date) / price(quarter-end of the earliest quarter in
the lookback window where a qualifying manager bought) − 1, earliest taken
across managers. Applied before the top_n cut so survivors backfill. Missing
price history passes. Distribution across candidates: p10 −25%, median +8%,
p90 +63%; 16% are up more than 50%.

| Cap | 2015–17 | 2018–20 | 2021–23 | 2024–26H1 | FULL | names/q | cash mo |
|---|---|---|---|---|---|---|---|
| none | 24.52 | 31.69 | 19.90 | 32.61 | **22.70** | 4.90 | 1 |
| UP ≤ +20% | 23.09 | 27.66 | 21.30 | 20.07 | 19.84 | 3.80 | 7 |
| UP ≤ +30% | 22.75 | 27.23 | 19.69 | 20.83 | 20.32 | 4.04 | 7 |
| UP ≤ +50% | 22.90 | 29.33 | 20.70 | 28.78 | 20.95 | 4.47 | 7 |
| UP ≤ +60% | 23.17 | 29.32 | 18.34 | 30.83 | 20.85 | 4.63 | 4 |
| UP ≤ +75% | 23.17 | 30.79 | 18.33 | 31.90 | 21.23 | 4.76 | 1 |
| **UP ≤ +100%** | 24.29 | 31.94 | 19.90 | 32.18 | **22.06** | 4.84 | 1 |
| UP ≤ +125% | 24.29 | 31.94 | 19.90 | 31.07 | 22.04 | 4.86 | 1 |
| UP ≤ +150% | 24.29 | 31.69 | 19.90 | 31.85 | 22.63 | 4.88 | 1 |
| ABS ≤ 20% | 23.53 | 27.72 | 17.39 | 20.29 | 20.49 | 3.35 | 13 |
| ABS ≤ 50% | 22.90 | 29.33 | 19.91 | 28.79 | 21.02 | 4.37 | 7 |

Every threshold underperforms no filter. The cost curve is flat above +75%
and falls off a cliff below it — tight caps both drop the winners and starve
the book into cash. Two-sided (ABS) variants are strictly worse than the
one-sided cap at the same level, so only upside is capped.

**+100% adopted** at ~0.6pt/yr, binding on ~6% of candidate-quarters. Ship
it as an adherence device, not as alpha. The 150%/200% rows converge to "no
cap" because almost nothing exceeds those moves; their edge over +100% is
2–3 individual names, not a pattern.

A finer version would use each quarter's VWAP rather than the quarter-end
close as the managers' cost proxy. Untested; unlikely to flip a result this
one-sided.

---

## 7. Quant screen ablation (2026-08, post-adoption)

Question: which of the 11 `pass_*` flags carry the screen, and can it be
simplified? Run under the full production rule set (HC 10%/6Q, MF rank-only,
price cap +100%, top 7, macro gate, 20% sizing cap). Baseline FULL 22.06.

### Leave-one-out (drop one flag, keep the other 10)

| dropped | FULL | Δ | note |
|---|---|---|---|
| quality_gate | 20.39 | **−1.67** | hurts every window; only flag that shrinks the book |
| clean_earnings | 21.55 | −0.51 | +10.3pt 2024–26 vs −6.8pt 2021–23 — single-name noise |
| revenue | 21.88 | −0.18 | |
| loss_year | 21.90 | −0.16 | |
| franchise | 21.93 | −0.13 | |
| maturity_cliff / depository / etf | 22.06 | 0.00 | never bind on a top-7 name |
| intcov | 22.08 | +0.02 | flat full-period but −5.9pt in 2024–26H1 alone |
| leverage | 22.38 | +0.32 | |
| cash_conversion | 22.46 | +0.40 | one window (2018–20), a handful of names |
| **all 11 dropped** | 20.92 | −1.14 | |

No single flag except quality_gate matters, yet dropping all 11 costs
1.14pt: the flags **overlap** (an overleveraged name usually also fails
intcov and the quality gate), so each is individually redundant while the
conjunction does real work. Every "only one flag" variant lands 0.9–1.6pt
below baseline.

### Extending quality_gate to unclear + cyclical — rejected

The gate only evaluates trad-ops and asset-light; unclear (3,171 rows) and
cyclical (1,431) get just the weaker `pass_franchise` bar (8–10% ROIC).
Built archetype-appropriate gates: unclear = cash-free ROC
(EBIT / (max(NWC,0)+net PP&E), same formula as `lib/ranks.roc`) ≥ 15% +
3y-avg FCF ≥ 0; cyclical = EBIT positive ≥ 3 of 5 yrs + 5y-mean ROIC ≥ 10%
+ net debt/EBITDA ≤ 3.

| variant | FULL | train 15-23 | holdout 24-26 | names/q |
|---|---|---|---|---|
| base (no new gates) | 22.06 | 17.34 | 32.18 | 5.09 |
| +unclear gate | 21.77 | 17.11 | 30.64 | 4.98 |
| +cyclical gate | 22.06 | 17.37 | 27.31 | 4.96 |
| +both | 21.75 | 17.10 | 25.48 | 4.84 |

Both hurt; every threshold knob is monotone in the wrong direction (no
interior optimum). The blocked names explain why: the unclear gate rejects
reinvest-ahead-of-earnings compounders (NFLX, SHOP, SE, NOW, SPOT), and the
cyclical gate rejects trough-recovery names (LNG, PXD, MRVL, EQT, VAL) —
exactly the 2024–26 drivers. The "ungated buckets" were not a hole;
`pass_franchise`'s looser bar is the right amount of work. Code kept in
`lib/screen.py` + `config.yaml` (`quality_gate.unclear` /
`quality_gate.cyclical`) but **disabled**.

### Group ablation — can the screen be simplified?

11 flags grouped into 4 concepts, all 16 subsets run (excludes always on):
S solvency (leverage, intcov, maturity_cliff), E earnings-reality
(clean_earnings, loss_year, cash_conversion), Q quality (quality_gate,
franchise), G growth (revenue). Picked on train 2015–2023 only.

| groups | train | 2021–23 | holdout | FULL | names/q |
|---|---|---|---|---|---|
| Q | 18.73 | 13.22 | 36.44 | 21.67 | 5.91 |
| EQ | 18.51 | 21.07 | 27.28 | 22.03 | 5.40 |
| QG | 18.51 | 13.22 | 36.83 | 21.98 | 5.73 |
| **none** | 17.98 | 12.55 | 30.95 | 20.92 | 6.80 |
| SEQG (current) | 17.34 | 19.90 | 32.18 | 22.06 | 5.09 |
| SE | 16.77 | 13.93 | 21.73 | 20.10 | 6.02 |

Signal: every Q-containing set ranks top-half, every Q-less set except
"none" ranks bottom-half; adding E lifts the 2021–23 window from ~13% to
~21% in every Q set. But **"none" out-trains the full screen** (17.98 vs
17.34) — when zero filters beats eleven on the selection metric, the train
spread (16.4–18.7) is noise. Holdout values swing 21–42% across
one-group differences because each difference is 2–3 names in a ~5-name
book (SQ's 42% holdout is one energy name).

**Decision: keep the full 11-flag screen.** The data lacks the power to
rank screen designs, and the burden of proof for changing a validated
production rule is not met by a noise-ranked table. If simplicity is ever
wanted as an operational (not empirical) choice, EQ — clean_earnings,
loss_year, cash_conversion, quality_gate, franchise — is the defensible
5-flag subset: top-4 on train, best worst-window, FULL 22.03 vs 22.06.

## 8. Mechanics, taxes and validation (2026-08, scratchpad session)

Ran on a harness that reproduces `outputs/windows.csv` exactly (PROD FULL XIRR
0.220575, 0.0000 pt across all 10 window/strategy cells). Scripts were
scratchpad-only and are not in the repo; the conclusions below are.

### The noise floor is ~2.6 pt of holdout excess

Changing **only the day of month the DCA buys** (5/10/15/20/25) moves FULL XIRR
by 0.1 pt but holdout excess from 6.44 to 9.08 pt. Any holdout-excess difference
below ~2.6 pt is calendar luck. This retroactively puts several results in this
log inside error bars — including the price cap's 0.6 pt/yr cost (§6) and most
of the leave-one-out flag deltas (§7).

### Four fixed windows understate tail risk; use rolling windows

Over 102 overlapping 3-year windows (monthly step) PROD beats SPY 84% of the
time, median +8.4 pt — but **p10 is −6.6 pt and the worst is −14.4 pt**, while
the worst *fixed* window in `windows.csv` reads +8.2 pt. Recommend
`p10_rolling3y_excess` as the risk metric for future variant work.
Caveat: a 3-year window cannot evaluate any rule with a horizon longer than
itself (see the max-age result below) — use 7-year windows for those.

### Rotation: large pre-tax gain, negative after tax

`run_window` never sells, and the selected list churns **3.7 of ~5.1 names per
quarter**, so never-selling accumulates 92 tickers over 11 years. Selling names
that drop off the list is therefore a real strategy change, not a tweak:

| variant | FULL XIRR | after tax (37/20) | turnover |
|---|---|---|---|
| never sell | 22.06% | **19.50%** | 0% |
| hard_rotate (30 bps) | 25.50% | — | 723%/yr |
| exit_on_drop (30 bps) | 26.60% | **17.58%** | 711%/yr |

Full rotation pays **$143k of tax on $137k invested** and its 4.5 pt pre-tax
edge becomes a 1.9 pt deficit. **Rejected for a taxable account**; it still wins
pre-tax, so it remains open for a tax-sheltered sleeve.

### Max-age exits — rejected, and a warning about how they look

A "sell after N years" clock raises FULL XIRR (3y 24.9%, 5y 25.2%, 6y 26.4%) at
a fifth of full-rotation turnover, and appeared optimal at 6y in all three tax
regimes. It does not survive:

- **Moving the clock 3 months swings FULL XIRR up to 2.9 pt with no pattern**
  (5.25y 23.73%, 5.5y 26.61%, 6.0y 26.35%, 6.25y 24.25%). Not a parameter.
- On **54 rolling 7-year windows** (long enough for the clock to fire),
  never-selling has the best floor: min +0.03, beats SPY in **100%** of windows.
  Every clock introduces losing windows (2y min −2.71, 3y −2.39, 5y −0.94).

**Never-selling now stands on evidence, not on the absence of a test.**

### Survivorship is ~1.6 pt/yr and is NOT fixable with better delisting data

The 27% of `screen_history.csv` tickers missing from `prices.parquet` overstates
the problem: only **17 of 132 HC-qualifying names (13%)**, occupying **24 of 229
selected slots (10.5%)**, mostly 2014-2017. Twelve of the 17 are *acquisitions*
(Allergan, EMC, Time Warner, TWC, Medivation, IHS Markit, CDK, Stamps.com,
WebMD, Michaels, Aerojet, Sapiens), two bankruptcies, three data gaps.

Reinstating them with synthetic paths costs 1.58–1.70 pt of FULL XIRR under any
assumption — and **1.55 pt even when they are given exactly SPY returns.** The
mechanism is not their performance: `run_window` silently drops unpriced picks
from `usable` and spreads that month's money over the survivors, concentrating
the book into hindsight winners. Only filling the *slots* fixes it.

**Every FULL XIRR in this repo is ~1.6 pt too high** (PROD ≈ 20.5%, not 22.06%).
Variant *comparisons* are unaffected — all arms inherit the same gap.
To close it: backfill the 17 names above (merger 8-K prices; bankruptcies at
last trade), not all 616 tickers.

### The edge is in the screen, and it is not fitted

Two validation tests, both previously unrun:

- **Cohort test** (each quarter's picks on their own forward return, no
  accumulation, vs SPY over the same interval): **+6.7 pt at 12 months, +16.0 at
  24, +28.5 at 36**, t-stat 1.57 → 2.88 → 3.25. The edge is in selection, not in
  the accumulated book. This also explains why exits hurt: picks keep
  outperforming for years after selection.
- **Walk-forward** (config chosen annually from a 24-point grid using only data
  up to that date, one continuous DCA book, 2019-01→2026-05): walk-forward
  **37.69%** vs shipped config 32.50% vs SPY 17.60%. Walk-forward *beats* the
  fitted config and wins 79% of 24 overlapping start dates. **There is no
  fitting premium to subtract.**

  *Methodology warning:* running each year as its own DCA segment instead gives
  a spurious −8.94 pt and a fake +10 pt "fitting premium" — a restarted DCA has
  ~6 months of average money at risk, so segment XIRR is driven by its final
  months (one 5-month stub annualized SPY at 60%). Do not evaluate this strategy
  in short independent DCA segments.

### Outcome dispersion: 56% win rate, carried by outliers

Across 210 individual pick-quarters with 12-month returns: win rate **56%**,
mean excess +9.30 pt, **median only +3.03 pt**. Dropping the top contributor
(TSEM, +516%) takes the mean to +6.88; dropping the top 10 of 210 takes it to
+2.04. The *portfolio* still beats SPY in 66% of 1-year, 84% of 3-year and 100%
of 7-year windows — positive skew at the portfolio level — but expect multi-year
stretches with no visible edge.

**Median pick excess has decayed**: +5.2 pt (2014-2019) → +2.9 pt (2020-2025),
while the mean rose on rarer, larger outliers. Consistent with a partially
arbitraged, publicly documented effect (13F cloning is an established literature
and an ETF category).

### Adopted / not adopted from this session

- **`mf.top_n: 7 → 5`** — the one change that improves the bootstrap floor,
  median and p95 together (200 ticker-drop draws: p5 2.45/med 7.18/p95 8.40 vs
  PROD 2.16/6.39/7.57) at zero turnover, tax or rule cost. **Not yet applied to
  `config.yaml`.**
- **Not adopted:** rotation and max-age (above); `hc_min` > 0.10 (0.20 posts the
  highest FULL XIRR in the study, 24.51%, while sitting in cash 43 of 137 months
  and beating SPY in 50% of 7-year windows — the clearest example in this log of
  FULL XIRR selecting a broken variant); stage-level simplification (a 4-rule
  version scores the same as the 16-rule PROD on bootstrap, neither better nor
  worse — simplify only if you value fewer moving parts).
- **Do not wire in:** `quality_tier` is *inverted* as a return predictor
  (Marginal 28.7% forward 1y, Elite 22.0%, Average 13.6%); **manager track
  record is actively harmful** — 288 of 325 HC name-quarters come from a single
  manager, but following the top-8 managers by 2015-2020 returns yields 15.5%
  in 2021-2026 vs 29.2% for everyone else.

## Rejected / not pursued

- **Shorter lookbacks (1q, 2q)** — full-period indistinguishable from 4q but
  thinner books and empty quarters; the apparent recent-window edge is
  momentum exposure that did not pay pre-2018.
- **Matching book size via lower thresholds** (1q/3%, 1q/5%, 2q/5%) — all
  1–3pt worse full-period.
- **Two-sided price bands** — dominated by the one-sided cap.
- **Holder-conviction HC** — §8; adds consensus mega-caps, halves the
  holdout at 10%; the flattering 20% version is appreciation-driven
  hindsight, not conviction.
- **Archetype gates for unclear/cyclical** — §7; block the compounders and
  trough-recovery names the strategy exists to find. Shipped disabled.
- **Screen simplification (Q-only or EQ)** — §7; train data cannot separate
  screen designs ("none" out-trains all 11 flags), so the validated full
  screen stands.
- **`mf_pct ≤ 0.50` hard filter** — retained as a config option
  (`mf.pctile_cutoff`) but disabled; ranking alone scored better on both
  robustness measures.

## Known limitations of this log

- `backtest/sweep.py` does **not** implement the price-runup cap; the cap was
  evaluated separately on top of the selected variant (§6). A sweep over
  cap × the rest of the grid was not run.
- All figures come from one price cache (`backtest/cache/prices.parquet`),
  which drops some delisted tickers — survivorship pressure is upward, and §8
  sizes it at **~1.6 pt/yr** on FULL XIRR.
- The 13F panel carries no filing-date column, so the 50-day formation lag is an
  assumption rather than a verified fact. Amendments are 3.2% of rows and 96.5%
  of manager-quarters contain none, so the exposure is small — but a manager who
  files late is silently treated as on time.
- Macro-gate PIT market caps use Compustat `prcc_f × csho` at the fiscal
  datadate rolled forward by price return; shares outstanding can be up to
  550 days stale, so names near the threshold could flip.

---

## 9. Do the quant filters actually avoid bad companies? (full-universe test)

§7 measured the 11 screen flags by dropping one at a time from the production
pipeline and reading FULL XIRR. That test is weak twice over: the candidate
pool is the HC set (~132 names, 288 of 325 name-quarters from one manager), and
§8 then showed a ~2.6 pt noise floor that swallows most of those deltas. It
also asks the wrong question — the flags exist to avoid disasters, not to pick
winners, and disaster-avoidance is a left-tail claim about a cross-section.

Tested directly instead, on the whole Compustat panel.
`backtest/filter_efficacy.py`, outputs `backtest/outputs/filter_efficacy_*`.

**Setup.** 105,225 firm-years (14,525 firms, cap ≥ $50M, USD) scored by the
production chain — `per_gvkey_metrics` → `tag_archetype` → `quality_gate` →
`derive_flags`, unmodified, no 13F input. Grain is firm-YEAR, not firm-quarter.
Returns are in-panel `adj_px = prcc_f / ajex`, fiscal-year to fiscal-year, at
1/3/5/10y. Metric is the rate of severe drawdown (return < −50%) among names a
filter REJECTS minus the rate among names it KEEPS; positive = the filter is
rejecting worse companies. Mean return is reported but is not the objective.

Three things make the numbers trustworthy, and one makes them conservative:

- **Delisted firms are retained, not dropped.** Every firm that stops reporting
  is classified by `dlrsn` and contributes a return: `acquired` (01/03) and
  `failed` (02/04/05/07/09/20) at last observed price, bankruptcy forced to
  −100%, `dropped_unknown` (10, 2,585 gvkeys, genuinely ambiguous) kept in its
  own column. Silently dropping unpriced names is the exact mechanism §8 found
  was inflating FULL XIRR by ~1.6 pt.
- **`costat` is never used to filter history.** It is a static as-of-today flag;
  filtering on it would delete 37.6% of the 2015 opportunity set.
- **CIs are a cluster bootstrap over gvkey** (1,000 draws). One firm supplies up
  to 16 firm-years and at H=10 neighbouring rows share 9 of 10 years, so
  independent-sample CIs are ~4x too narrow and would make everything look
  significant.
- **Conservative:** returns are dividend-blind, which penalises mature payers —
  who cluster in the PASS arm. Acquisitions realise no deal premium (last fiscal
  price ≈ formation price), and acquisitions are *more* common among rejects
  (18.3% vs 10.2% at 5y), so that also penalises the pass arm.

**The screen as a whole works, and the effect is large.**

| horizon | arm | n | severe-dd | failure | p10 | median |
|---|---|---|---|---|---|---|
| 5y | passes_quant | 29,731 | **8.7%** | **0.8%** | −0.45 | +6.9% |
| 5y | rejected | 38,124 | 23.7% | 3.1% | −0.87 | 0.0% |
| 10y | passes_quant | 16,242 | **13.2%** | **1.5%** | −0.62 | +7.8% |
| 10y | rejected | 19,653 | 26.6% | 4.5% | −0.93 | +0.4% |

Failure rate is cut by ~3x at both horizons. This is a much cleaner result than
anything in §7, because n is ~10,000x larger and the metric matches the flags'
actual job.

**Per-filter, marginal (within names passing the other 10) and size/sector
matched.** Matching pairs each rejected firm-year with up to 3 kept firm-years
in the same fyear, same gsector, nearest log-cap (±0.5) — a filter that only
dodges micro-cap biotech scores well raw and collapses when matched.

| filter | marginal 5y | matched 5y | matched 10y | verdict |
|---|---|---|---|---|
| `pass_loss_year` | +46.2% | **+14.4%** | **+13.7%** | strongest, survives everything, 9/9 sectors |
| `pass_franchise` | +16.4% | **+7.2%** | **+10.9%** | robust, grows with horizon |
| `pass_intcov` | +12.4% | **+10.4%** | **+9.4%** | robust, 10/10 sectors |
| `pass_leverage` | +5.0% | +2.4% | +4.3% | real but modest |
| `pass_revenue` | +10.0% | +2.0% | +2.0% | mostly a size/sector proxy |
| `pass_cash_conversion` | +11.0% | +0.4% | −0.2% | **entirely** a size/sector proxy |
| `pass_clean_earnings` | +12.3% | −0.1% | −1.1% | **entirely** a size/sector proxy |
| `pass_quality_gate` | +2.1% | **−4.1%** | **−6.0%** | rejects *safer* names once matched |
| `pass_depository_exclude` | −7.1% | **−14.2%** | **−17.5%** | rejects far safer names |
| `pass_maturity_cliff` | — | — | — | not measurable (118 rejects / 89 firms at 5y) |
| `pass_etf_exclude` | — | — | — | not measurable (19 firms); dead on this universe |

Four findings worth acting on:

1. **Four filters carry the screen.** `loss_year`, `franchise`, `intcov`,
   `leverage` keep a positive matched delta at both horizons and in all three
   cap terciles. These are the ones doing real work, and notably §7 ranked three
   of them as individually droppable — the conjunction hid their value because
   FULL XIRR on ~5 names/quarter cannot resolve it.
2. **Three filters are size/sector proxies.** `clean_earnings`,
   `cash_conversion` and (mostly) `revenue` post large raw deltas that go to
   ~zero once matched on year, sector and cap. They are not detecting bad
   companies; they are detecting small companies in risky sectors. That does not
   make them useless — the strategy does not size-match — but their contribution
   is not what the flag names claim.
3. **`pass_quality_gate` rejects safer-than-average names once matched**
   (−4.1% at 5y, −6.0% at 10y). It is also the only flag where missing data
   FAILS rather than passes (`lib/screen.py`, trad-ops `no_roic_data`,
   asset-light `no_roic_or_gm`), and its rejects are 12,291 trad-ops + 10,645
   asset-light firm-years. §7 gave it the largest drop-delta (−1.67 pt), so on
   this evidence the gate helps returns while *not* helping disaster avoidance.
   Both can be true — a high-ROIC hurdle is a quality/return filter, not a
   safety filter. Worth keeping, but not on avoidance grounds.
4. **`pass_depository_exclude` is the strongest negative in the study.** The
   banks it excludes had a 2.0% severe-drawdown rate vs 18.5% for what the
   screen keeps, a 0.7% failure rate, and a **+23.3% median 5y return**. Over
   2010–2025 US depositories were the *safe* corner of the market. The exclusion
   is deliberate operator policy (see CLAUDE.md) and this does not argue for
   reversing it — but it is a policy choice with a measured cost, not a
   risk control.

**Robustness.** Re-running with bankruptcy valued at last reported price rather
than −100% (`--no-bankrupt-zero`) changes no ranking at either horizon; the
largest matched-delta move is 1.0 pt (`maturity_cliff`, already unmeasurable).
Full comparison in `filter_efficacy_*_nobz.csv`.

**Limits.** Annual granularity only, so nothing here speaks to timing or
drawdown path. Dividend-blind. Deal premia unrealised. `dropped_unknown`
(dlrsn 10) is reported separately rather than assigned to either outcome. The
panel starts at fyear 2009, so 10y observations come from 2010–2015 formations
(35,895 firm-years, 8,393 firms) and are therefore concentrated in one market
regime.

---

## 10. The 4-rule screen: full-universe and strategy backtests

§9 found that only four of the eleven flags — `pass_loss_year`, `pass_intcov`,
`pass_franchise`, `pass_leverage` — keep a positive size/sector-matched
disaster-avoidance delta at both 5y and 10y. This section tests a screen built
from just those four, on both measurement axes. The depository exclusion stays
in force throughout as separate operator policy (CLAUDE.md), so only the quant
screen changes. Run with:

```
python backtest/run_windows.py --flags pass_loss_year,pass_intcov,pass_franchise,pass_leverage,pass_depository_exclude --out windows_4rule.csv
```

`load_screen(flags_subset)` in `backtest/run_windows.py` now takes an optional
flag subset; passing None is the production path and still reproduces
`windows.csv` exactly (PROD FULL 22.06%).

### Full universe: the 4-rule screen is BETTER at avoiding bad companies

Same 105,225-firm-year panel as §9.

| horizon | screen | keeps | severe-dd kept | failure kept | severe-dd rejected | failure rejected |
|---|---|---|---|---|---|---|
| 5y | 11-rule | 43.8% | 8.7% | 0.80% | 23.7% | 3.07% |
| 5y | **4-rule** | **60.1%** | 10.1% | 0.90% | **27.7%** | **3.85%** |
| 10y | 11-rule | 45.2% | 13.2% | 1.48% | 26.6% | 4.47% |
| 10y | **4-rule** | **62.6%** | 14.2% | 1.64% | **31.2%** | **5.59%** |

Separation (rejected minus kept), with 95% gvkey-cluster bootstrap CIs:

| horizon | screen | severe-dd delta | failure delta |
|---|---|---|---|
| 5y | 11-rule | +15.0% [+14.1, +16.0] | +2.28% [+1.96, +2.61] |
| 5y | **4-rule** | **+17.6% [+16.5, +18.7]** | **+2.96% [+2.55, +3.37]** |
| 10y | 11-rule | +13.4% [+12.1, +14.8] | +2.98% [+2.38, +3.58] |
| 10y | **4-rule** | **+17.0% [+15.5, +18.4]** | **+3.95% [+3.20, +4.64]** |

The 4-rule screen separates better on both metrics at both horizons, and the CIs
do not overlap at 10y. It rejects a smaller but much more concentrated set of
genuinely dangerous companies while keeping 60% of the universe rather than 44%.
Seven of the eleven rules were rejecting names that were not, in fact, dangerous.

Under size/sector matching the gap becomes stark:

| horizon | screen | severe-dd kept | severe-dd rejected | matched delta |
|---|---|---|---|---|
| 5y | 11-rule | 12.9% | 13.5% | **+0.6%** |
| 5y | **4-rule** | 14.7% | 22.5% | **+7.8%** |
| 10y | 11-rule | 18.0% | 17.1% | **−0.9%** |
| 10y | **4-rule** | 19.0% | 27.7% | **+8.7%** |

**Matched, the full 11-rule screen does not separate at all** (+0.6% at 5y,
−0.9% at 10y) while the 4-rule screen separates strongly. The seven discarded
rules are not merely redundant — collectively they dilute the screen back to
noise, because their rejections are driven by size and sector rather than by
danger. This is the strongest single result in the log for the disaster-
avoidance question.

### Strategy backtest: slightly worse, inside the noise floor, one bad window

| window | 11-rule PROD | 4-rule PROD | Δ | excess vs SPY (11r → 4r) |
|---|---|---|---|---|
| 2015-2017 | 24.29% | 26.05% | +1.77 | +8.16 → +9.92 |
| 2018-2020 | 31.94% | 28.81% | −3.13 | +12.57 → +9.44 |
| 2021-2023 | 19.90% | 10.52% | **−9.38** | +9.24 → **−0.14** |
| 2024-2026H1 | 32.18% | 31.45% | −0.73 | +9.07 → +8.34 |
| **FULL 2015-2026** | **22.06%** | **20.92%** | **−1.14** | +6.20 → +5.06 |

FULL is 1.14 pt lower — comfortably inside §8's ~2.6 pt noise floor, so on its
own that difference is not interpretable. The 2021-2023 window is not: −9.38 pt
is well outside it and needs a cause, not a shrug.

Diffing the picks quarter by quarter gives one. The 4-rule screen passes 60.2%
of HC candidates versus 39.3% for the 11-rule screen, so it fills quarters that
were previously starved:

```
2021Q1  11r= 2 names   4r= 6   ADDED: BABA, CVS, EBAY, IFF
2021Q2  11r= 1 name    4r= 4   ADDED: BABA, CRM, CVS
2021Q3  11r= 1 name    4r= 5   ADDED: BABA, CRM, DIS, LMT
2021Q4  11r= 4 names   4r= 7   ADDED: BMY, GD, GDDY, IFF   DROPPED: NVDA
```

In 2021 the 11-rule screen was producing one or two names a quarter — the top-7
cut was nowhere near binding, the screen was. The looser screen backfilled those
slots with 2021-vintage large caps, BABA in three consecutive quarters, and they
fell hard. It also dropped NVDA in 2021Q4. So the window's loss is a
concentration-and-vintage accident in a handful of names, exactly the
single-name noise §8 warns about ("holdout values swing 21-42% across
one-group differences"), not evidence that the four rules are unsafe.

### Reading the two results together

They do not conflict; they answer different questions.

- **As a safety filter, 4 rules beat 11**, decisively and with non-overlapping
  CIs. The matched result says the 11-rule screen's apparent safety is almost
  entirely a size/sector effect.
- **As a return filter, 11 rules are modestly ahead** (+1.14 pt FULL, inside
  noise), driven by one window in which the tighter screen's scarcity
  accidentally avoided a bad 2021 megacap vintage.

That the tighter screen wins on returns while losing on safety is consistent
with §9's per-flag finding: `pass_quality_gate` had the largest return
contribution in §7 (−1.67 pt when dropped) and a *negative* matched safety delta
(−4.1% at 5y). Several of the seven discarded rules are quality/valuation
filters wearing risk-filter names. Dropping them removes return, not risk.

**No parameter change is adopted here.** The 4-rule screen is better at the job
the flags are nominally for and no worse on returns than the noise floor can
resolve, but it more than doubles the pass rate (39.3% → 60.2%), which changes
how often the top-N cut binds and interacts with `mf.top_n` — untested in
combination. The honest recommendation is a joint sweep of `top_n` against the
4-rule screen before adopting either, since with 60% passing, the top-N cut
rather than the screen becomes the binding constraint.

**Limits.** The strategy comparison inherits every §8 caveat: ~2.6 pt noise
floor, four fixed windows that understate tail risk, and a ~1.6 pt survivorship
overstatement common to both arms. Rolling-window p10 and a ticker-drop
bootstrap — the metrics §8 says to actually judge on — have not been run for the
4-rule arm.

---

## 11. top_n sweep against the 4-rule screen

§10 declined to adopt the 4-rule screen because it more than doubles the pass
rate (39.3% → 60.2%), which shifts the binding constraint from the screen to the
top_n cut — and top_n was tuned against the old pass rate. This resolves that.

`backtest/sweep_topn_4rule.py`, output `backtest/outputs/sweep_topn_4rule.csv`.
Not `backtest/sweep.py`: that harness omits the price-runup cap (its own known
limitations say so) and scores on the worst of four fixed windows, which §8
shows understates tail risk. This runs the real PROD path from
`run_windows.build_selectors` — price cap before the cut, macro gate after, 20%
sizing cap — and ranks on **rolling 3-year p10 excess** (101 windows), with a
**ticker-drop bootstrap** (200 draws, 20% of tickers dropped, slots backfill)
as the second robustness measure. FULL XIRR is reported but not used to rank.

| screen | top_n | roll p10 | roll median | win rate | boot p5 | FULL excess | names/qtr |
|---|---|---|---|---|---|---|---|
| **4-rule** | **5** | **−0.04%** | +6.80% | **89.1%** | +1.56% | +6.03% | 4.6 |
| 4-rule | 7 | −0.58% | +8.78% | 88.1% | +1.47% | +5.06% | 6.0 |
| 4-rule | 10 | −1.14% | +9.33% | 87.1% | +1.61% | +4.19% | 7.5 |
| 4-rule | none | −1.18% | +6.66% | 87.1% | +1.45% | +3.76% | 8.9 |
| 4-rule | 15 | −1.46% | +7.77% | 87.1% | +1.20% | +3.90% | 8.5 |
| 11-rule | 5 | −4.46% | +7.87% | 86.1% | +1.68% | +6.95% | 3.9 |
| 4-rule | 3 | −5.95% | +5.67% | 71.3% | +1.45% | +7.40% | 2.8 |
| 11-rule | 3 | −6.79% | +4.25% | 73.3% | +2.52% | +7.93% | 2.7 |
| 11-rule | **7 (prod)** | **−7.03%** | +8.70% | 84.2% | +1.68% | +6.20% | 4.8 |
| 11-rule | 10 | −7.26% | +8.38% | 84.2% | +1.41% | +5.79% | 5.4 |
| 11-rule | 15 / none | −7.57% | +8.64% | 84.2% | +1.82% | +5.77% | 5.6 |

**The 4-rule screen beats the 11-rule screen on p10 at every top_n ≥ 5**, by
4.4 to 6.5 pt — far outside the ~2.6 pt noise floor. It is not a marginal call.

Head to head, 4-rule/top_n=5 against production 11-rule/top_n=7:

| metric | 4-rule top5 | 11-rule top7 | diff |
|---|---|---|---|
| rolling 3y p10 excess | **−0.04%** | −7.03% | **+6.99 pt** |
| rolling 3y win rate | **89.1%** | 84.2% | +4.9 pt |
| rolling 3y median excess | +6.80% | +8.70% | −1.90 pt |
| ticker-drop p5 | +1.56% | +1.68% | −0.11 pt |
| FULL XIRR | 21.89% | 22.06% | −0.17 pt |
| avg names/quarter | 4.6 | 4.8 | −0.2 |

Same portfolio size, same FULL return to within 0.17 pt, essentially identical
bootstrap floor — and the worst decile of 3-year windows improves from −7.03 pt
to break-even. A p10 of −0.04% means that over 101 rolling 3-year windows, the
variant almost never underperformed SPY meaningfully; the production config
gave up 7 pt in its bad decile.

This also reverses §10's reading. §10 saw the 4-rule screen 1.14 pt behind on
FULL XIRR and called it "modestly worse on returns", flagging the 2021-2023
window. The sweep shows that comparison was confounded by top_n: at its own best
top_n the 4-rule screen matches FULL return *and* removes most of the left tail.
§10's 2021-2023 hole was a top_n=7 artifact — with 60% of candidates passing,
7 slots pulled in marginal names (BABA three quarters running) that 5 slots
exclude. This is a fresh instance of §8's warning that FULL XIRR selects badly:
judged on FULL XIRR alone, 11-rule/top_n=3 "wins" the whole table at +7.93 pt
excess while posting a −6.79 pt p10 and a 73% win rate.

**Also notable:** the 11-rule screen's p10 is flat-to-worsening in top_n
(−4.46 → −7.57) and its FULL excess barely moves past 7, because at 39.3% pass
rate the screen binds and extra slots go unfilled — top_n=15 and top_n=none are
byte-identical. The 4-rule screen is the only arm where top_n is a live
parameter, which is exactly what §10 predicted.

### Recommendation

`mf.top_n: 5` with the 4-rule screen is the best variant in this log on §8's
own criteria — best p10, best win rate, return indistinguishable from
production. Two reasons to still not flip `config.yaml` on this run alone:

1. **The four rules were selected on the same price history this is scored on.**
   §9 chose them from the full Compustat universe on *fundamental* outcomes
   (blow-up and failure rates), not from this DCA backtest, so the
   contamination is much weaker than a normal in-sample fit — but it is not
   zero, and §5 already documents a case where widening a grid after seeing
   full-sample results compromised the train/holdout split.
2. **`mf.top_n: 7 → 5` is already marked adopted-but-unapplied in §5.** Config
   still ships 7. Applying top_n=5 and the 4-rule screen together confounds two
   changes; apply top_n=5 first, confirm it reproduces, then change the screen.

Suggested order: set `mf.top_n: 5`, re-run `run_windows.py`, then switch the
screen and re-run. Both steps are one-line config/`lib/screen.py` changes.

**Limits.** 101 rolling windows from one price history, all overlapping, so
they are not independent observations. The ticker-drop bootstrap separates the
arms barely (+1.56% vs +1.68% p5) — it says neither variant depends on a
handful of names, not that the 4-rule screen is more robust by that measure.
Every arm carries the same ~1.6 pt survivorship overstatement (§8). 7-year
windows, which §8 recommends for anything with a long horizon, were not run.

---

## 12. Open threads: deeper work on the 4-rule screen

**Decision as of 2026-08-23: no change adopted. Production stays on the 11-rule
screen with `mf.top_n: 7`.** §§9-11 make a strong case for a 4-rule screen at
`top_n=5`, but the evidence is asymmetric — the full-universe safety result is
large-sample and robust, while the portfolio result rests on 101 overlapping
windows of one price history. The items below are what would have to be settled
before revisiting. Nothing here is a bug; it is all unfinished measurement.

### Highest value first

1. **Decompose `pass_quality_gate`.** It is the only flag where missing data
   FAILS rather than passes (`lib/screen.py`: trad-ops `no_roic_data`,
   asset-light `no_roic_or_gm`). Its matched safety delta is negative (−4.1% at
   5y, −6.0% at 10y) while §7 gave it the largest return contribution
   (−1.67 pt when dropped). Split it into (a) the data-coverage effect and
   (b) the ROIC/GM hurdle, scored separately in `filter_efficacy.py`. If the
   negative delta is driven by (a), making missing data pass is a one-line
   change that may beat both the 4-rule and 11-rule screens. This is the
   cheapest open item with the highest chance of changing the answer.

2. **Test the matching specification.** §9's survivors were selected under one
   design: same fyear, same gsector, log-cap caliper ±0.5, up to 3 controls.
   Re-run with a tighter caliper (±0.25), an industry-relative (gind) match,
   and a propensity-score match on (log cap, sector, leverage, profitability).
   If the four survivors reorder, the §9 conclusion is specification-dependent
   and should be weakened. `pass_leverage` is the one to watch — it is the
   weakest survivor (+2.4 pt at 5y) and the most likely to fall out.

3. **7-year rolling windows for the top_n sweep.** §8 requires horizons longer
   than the rule being tested; §11 scored on 3-year windows only. 54 seven-year
   windows exist. A `top_n` change alters concentration, whose effect compounds
   over holding periods longer than 3 years.

4. **Walk-forward the screen choice.** Pick the surviving flags on 2010-2017
   Compustat outcomes only, then score the resulting screen on 2018-2026
   portfolio returns. §9 selected flags on fundamental blow-up rates rather than
   on this DCA backtest, so contamination is weak — but it is not zero, and §5
   documents a case where post-hoc grid widening compromised a train/holdout
   split. This is the test that would make the 4-rule result publishable rather
   than suggestive.

### Secondary

5. **Turnover and tax.** §11 compared gross returns. The 4-rule screen churns
   more in some quarters (2025Q3 turns over almost completely versus the
   11-rule book). Quantify realised turnover and after-tax return before
   adopting — the log has never costed turnover for any variant.

6. **Ticker-drop bootstrap barely separates the arms** (+1.56% vs +1.68% p5).
   It says neither variant leans on a handful of names; it does not rank them.
   A block bootstrap over calendar time would be the more informative test,
   since the failure mode of concern is a bad vintage (§10's 2021 BABA
   sequence), not a bad ticker.

7. **`pass_maturity_cliff` and `pass_etf_exclude` remain unmeasured** (89 and 19
   firms respectively pass the other ten). They are retained on the precautionary
   principle. `pass_etf_exclude` is structurally dead on a Compustat universe —
   ETFs are not in the panel — so it only ever binds via the 13F path.

8. **Sector-level detail behind the survivors.** §9 reports sector counts
   (`sectors 9/9`, `10/10`) but not which sectors dissent. `pass_revenue` and
   `pass_cash_conversion` hold in only 3 of 5-6 measurable sectors at 10y;
   worth knowing whether the failures cluster in one industry.

### If adopting later, do it in this order

`mf.top_n: 7 → 5` first (already marked adopted-but-unapplied in §5; expected
FULL 22.06% → 22.80%, p10 −7.03 → −4.46), re-run `run_windows.py` and confirm
it reproduces, and only then change the screen in `lib/screen.py`. Applying both
at once confounds two changes and makes a later regression un-diagnosable.

---

## 13. CRSP re-measurement, the 13F filter's value, and a drawdown contribution rule (2026-08-24, scratchpad session)

First session in this log to run the strategy on **CRSP monthly data instead of
the yfinance daily cache**. That matters for every number below: CRSP is
delisting-complete (10,652 real delistings retained, terminal returns supplied
by CRSP including bankruptcies at −1.0) and `MthRet` is dividend-inclusive
total return. Selection is unchanged — `run_windows.build_selectors` is reused
verbatim, so PROD here is production's exact ticker list; only the return source
and the contribution grid differ (monthly month-end vs daily-on-the-20th).

Scripts are scratchpad-only and not in the repo. Window 2014-06 → 2025-12
(139 months, $1,000/month), bounded by CRSP's end and by `revt_cagr_3y` needing
four annual Compustat rows (only 65% of gvkeys have that by 2014Q1, 6.5% by
2013Q1 — starting earlier lets missing data pass the screen and inflates results).

### 13.1 The published 22.06% reconciles to 16.73%, and it is mostly the window

| Step | XIRR | Δ |
|---|---|---|
| `run_windows.py` PROD FULL 2015-01 → 2026-05 (published) | 22.06% | — |
| same engine, end at 2025-12 (CRSP's last month) | 19.67% | **−2.39** |
| same, start 2014-06 | 19.18% | −0.49 |
| CRSP monthly total return, same window | **16.73%** | **−2.45** |

**Survivorship was measured directly here and is smaller than §8's estimate.**
Re-running the CRSP book restricted to the 96 tickers yfinance covers gives
16.96% vs 16.73% for all 112 — a **+0.23 pt** effect, not ~1.6 pt. The 16 names
yfinance lacks are not uniformly dead: BBBYQ −99.8%, TLRDQ −98.6%, WBA −75% are
offset by STMP +920%, ARCH +529%, SPNS +382%. Dropping them removed roughly as
much upside as downside. §8's ~1.6 pt figure was estimated across the whole book
and should not be applied to the PROD arm specifically.

The largest single factor is the five months 2026-01 → 2026-05 (−2.39 pt). Under
DCA the last months hold the most money, so FULL XIRR is dominated by the
endpoint — the same fragility §8 found when changing the buy day-of-month.
**Do not quote FULL XIRR as the strategy's expected return.**

### 13.2 Rolling windows agree across both data sources

| Engine | PROD median XIRR | SPY median | excess p10 | excess median | winrate | n |
|---|---|---|---|---|---|---|
| yfinance daily (2015-01 → 2026-05) | 25.33% | 14.33% | −6.70% | +8.63% | 84% | 101 |
| CRSP monthly (2014-06 → 2025-12) | 24.21% | 13.62% | −0.02% | **+10.34%** | 89% | 103 |

The 1.7 pt spread is inside the ~2.6 pt noise floor. Note the rolling median
(24-25%) exceeds both FULL figures — a continuous 11.5-year book must live
through the bad stretches that a median over overlapping windows averages away.
Non-overlapping calendar books: 2014-16 **11.74%**, 2017-19 **21.06%**,
2020-22 **−3.31%**, 2023-25 **31.23%**. The 2020-22 book is the reason FULL
(16.73%) sits below the rolling median.

### 13.3 The 13F filter is where the value is

Same screen, same MF ranking, same engine, same window; the only difference is
whether HC conviction gates the candidate pool. The universe arm additionally
carries a ≥$1B cap floor and drops SIC 6xxx (MF's ROC denominator is meaningless
on insurance balance sheets — they swept the top 20 by `mf_pct` otherwise), so
this is not a perfectly clean single-variable test.

| Arm | FULL XIRR | rolling median excess | p10 | winrate |
|---|---|---|---|---|
| PROD (HC ∩ MF, top 7) | **16.73%** | +10.34 pt | −0.02 | 89% |
| HC (no MF cut, no overlays) | 16.90% | +9.94 pt | +0.38 | 90% |
| Universe top-10 by MF, neversell | 11.23% | +0.21 pt | **−13.43** | 50% |
| SPY | 14.86% | — | — | — |

A 5.5 pt gap with a 39-point winrate difference, far outside the noise floor.
The universe arm concentrated into homebuilders — PHM (30 quarters), LEN (28),
NVR (23), TOL, TPH, TMHC, MHO, MTH, KBH — plus DLX (26) and VIAB, i.e. one
leveraged cyclical bet. **HC conviction may be acting partly as an accidental
diversification filter**; a sector-capped universe arm was not run and would
separate the two explanations.

**PROD ≈ HC on this data** (16.73 vs 16.90, and HC is marginally ahead on both
FULL and rolling). The MF top-7 cut, price cap and macro gate are collectively
adding nothing measurable. Not a reason to remove them — the price cap is a
deliberate behavioural constraint (§6) and the macro gate insures against a
state that barely occurred in-sample — but they are currently unpaid-for.

### 13.4 A hold-until-broken variant, after tax — rejected

Tested at the user's request: universe top-10, sell when a name fails the quant
screen or its `mf_pct` drifts past 0.25, per-lot FIFO with 30% short-term /
10% long-term on realized gains, losses carried forward against gains only.

| Arm | terminal (after tax) | XIRR pre | XIRR after | tax paid | median hold |
|---|---|---|---|---|---|
| HOLDBREAK | $197,179 | 6.37% | **5.92%** | $7,628 | 1.67 yrs |
| ROTATE (quarterly) | $214,554 | 7.66% | 7.31% | $11,397 | 1.00 yr |
| NEVERSELL | $253,336 | 10.79% | 10.02% | $13,164 | — |

Selling actively hurt: HOLDBREAK trails NEVERSELL by 4.1 pt after tax and only
$7.6k of that is tax. Trigger attribution shows why — `screen_fail` (30 exits)
realized **−$5,780** of net losses and `left_universe` (12 exits) **−$8,390**;
both rules mostly sold names *after* they fell. The one profitable trigger was
`mf_exit`, **+$12,065 over 5 exits**. Selling winners that got expensive worked;
selling losers that broke did not. Consistent with §8's rejection of rotation
and max-age exits.

`mf_pct > 0.25` fires on only ~2.2% of positions per quarter (5 of 55 exits) —
near-inert, as predicted before the run.

### 13.5 Adopted: double the monthly contribution after an SPY drawdown

**Rule: contribute 2× the normal monthly amount when trailing 6-month SPY total
return is below −5%, 3× when below −10%. Base contribution otherwise.**

This is a **contribution policy, not a selection rule** — it changes how much is
deposited, not what the pipeline buys. `run_quarter.py` is unaffected.

| Rule (6m lookback) | invested | XIRR | Δ vs flat | timing edge |
|---|---|---|---|---|
| flat $1,000/mo (baseline) | $139,000 | 16.73% | — | — |
| 2× @ −5% | $151,000 | 17.94% | +1.21 pt | +0.207 |
| **2× @ −5%, 3× @ −10%** | $154,000 | **18.10%** | **+1.36 pt** | +0.216 |

Fires 12 of 139 months: 2015-09, 2015-10, 2016-02, 2019-01, 2020-04, and seven
months of 2022. It is essentially a fix for the −3.31% 2020-22 book in §13.2.

**Why it survives scrutiny.** Holding total dollars constant at $151,000 spread
evenly gives 2.777× — identical to baseline — so the entire gain is *timing*,
not the extra money. Doubling on 12 **random** months (500 placebo draws)
averages 2.766× (sd 0.057); the actual rule's 2.984× is beyond every placebo
drawn. Lagging the signal 1-2 months barely changes it (2.927×, 2.986×), so it
does not require acting instantly on month-end data.

**Everything else tested made it worse:**

| Variant | Δ XIRR | why it fails |
|---|---|---|
| 3× flat instead of 2× | +0.99 | non-monotone in the multiplier (2× > 2.5× > 3× < 4× > 5×) — noise, same 12 months levered harder |
| 1.5× @ −2% + 2× @ −5% | **−0.25** | the −2% band is 6 shallow-pullback months that kept falling; `1.5×@−2 only` = +0.12 |
| + 2× when S&P PE < 20 | −0.03 | PE<20 fires 8 months, all 2014-06→2015-01; `PE<20 only` = −0.58 |
| + 2× when CAPE < 25 | +0.57 | no CAPE variant beats dip-only; best CAPE-only rule is +0.15 |
| dip extra → SPY sleeve | **−0.02** | dilutes the better-compounding asset at the best entry point |

**Both valuation overlays fail structurally, not for lack of data.** A full
2007+ TTM PE series and a 2011+ CAPE series were supplied and tested; CAPE
ranged 24.0-39.6 over this window and never got cheap in absolute terms. Within
2014-2025 there is no genuine cheap-valuation episode, only drawdowns — so a
valuation condition can either duplicate the drawdown signal or add noise. Both
indices also drift upward over the sample, making a fixed threshold approximately
a "buy early in the sample" rule rather than a valuation signal. A
CAPE-relative-to-trailing-mean version was built and is neutral-to-negative.

Routing the extra money to SPY (a diversification hedge for a 6-7 name book)
gives 16.71% vs 18.10% — the sleeve ends at $36,546 against a $386,028 PROD
book, ~9% of the portfolio compounding at ~15% instead of ~17-18%.

### 13.6 Limitations specific to this section

- **12 firing months, 7 of them 2022.** The dip rule's entire evidence base is
  one bear market. Do not expect a reliable +1.36 pt.
- **The 2×/3× tiering is not separable from flat 2×.** The −10% tier fires
  3 times at a 6-month lookback; +1.36 vs +1.21 rests on three months.
  `2×@−5/4×@−10` is *worse* (+0.71) than flat 2×, which is what noise looks like.
- **Requires holding cash in reserve** to fund the doubles. The backtest assumes
  the extra contribution is always available; it is not modelled as coming from
  anywhere.
- No transaction costs or slippage in any arm here.
- The universe arms (§13.3, §13.4) carry a ≥$1B floor and a SIC 6xxx exclusion
  that production does not, so "13F vs no 13F" is not a perfectly clean contrast.
- Loss carryforward in §13.4 is unlimited against future gains, with no
  $3,000/yr ordinary-income cap — mildly flatters the taxed arms.

## 14. Macro gate backfill (2026-11-16)

The macro gate used to run after the top_n cut, so a blocked slot stayed empty.
In 2026Q3 that left the book at six names (TSM blocked at a $1,937bn market cap
against a $1,651bn limit). The operator asked for blocked slots to be refilled.
`macro.backfill: true` now removes blocked names before the cut, the same way
the price cap works, so the next-ranked survivor takes the slot.
`backtest/run_windows.py --macro-backfill on|off` compares the two rules on
the same caches.

| Window | No backfill | Backfill | Δ |
|---|---|---|---|
| 2015–2017 | 24.29 | 24.29 | 0.00 |
| 2018–2020 | 31.94 | 31.94 | 0.00 |
| 2021–2023 | 19.90 | 19.48 | −0.42 |
| 2024–2026H1 | 32.18 | 32.38 | +0.20 |
| FULL | 22.06 | 22.10 | +0.04 |

The no-backfill arm reproduces the §8 baseline (FULL 22.06). The gate binds in
few quarters, and every difference is far below the 2.6 pt noise floor, so the
change is neutral on returns. It was adopted to keep the book at seven names.
Outputs: `backtest/outputs/windows_macro_{backfill,nobackfill}.csv`.
`backtest/sweep.py` and `sweep_topn_4rule.py` keep their own gate logic and
still apply the old no-backfill rule; update them before using them for a new
sweep.

## 15. Filing lag on the quant screen (2026-11-17, scratchpad session)

`lib/ranks.py` uses a Compustat row only when `datadate + mf.filing_lag_days`
(90) is on or before the formation date (quarter end + 50 days).
`lib/screen.py::run_screen` had no lag: it took the latest row with
`datadate <= quarter end`. In the screen history, 20.8% of rows have a
fiscal year that ended less than 90 days before formation, so the backtest
screen saw about one annual report in five before it was filed. Production
cannot do that (the live panel holds only filed reports), so backtest and
production were running slightly different rules.

Test: rebuild `screen_history.csv` three times from the same 13F and
Compustat data, moving the screen's `as_of` date, then run `run_windows.py`
PROD and 101 rolling 3-year windows. MF ranks keep their 90-day lag in every
arm. The no-lag arm reproduces the §14 baseline exactly.

| Window | No lag | 90-day lag | 365-day lag |
|---|---|---|---|
| 2015–2017 | 24.29 | 24.29 | 28.16 |
| 2018–2020 | 31.94 | 32.35 | 32.56 |
| 2021–2023 | 19.48 | 18.20 | 14.71 |
| 2024–2026H1 | 32.38 | 41.67 | 35.40 |
| FULL | 22.10 | 22.11 | 21.62 |
| Rolling 3y excess, p10 | −7.03 | −7.26 | −3.74 |
| Rolling 3y excess, median | 8.70 | 8.81 | 10.09 |
| Rolling win rate | 0.84 | 0.84 | 0.85 |

- 90-day lag: the selected set changes in 12 of 50 quarters, usually by one
  name. FULL and rolling are unchanged. The +9.3 pt in 2024–2026H1 is one
  swap (2023Q4 GSHD → TSEM; TSEM rose 7.5x and GSHD fell 59% from 2024-02 to
  2026-05). The look-ahead did not inflate the backtest.
- 365-day lag (the screen sees only reports at least a year old; with the
  550-day age window a row can be up to 915 days old): the set changes in 40
  of 50 quarters. FULL −0.48 pt, inside the noise floor. Rolling p10 +3.3 pt.
  2021–2023 −4.8 pt, mostly because stale data kept BABA from 2021Q1 to
  2022Q3 after fresher reports dropped it. No ticker-drop bootstrap was run,
  so the p10 gain is not established.

Reading: portfolio returns barely depend on how fresh the screen's data is.
The screen works as a filter for persistent problems (leverage, losses,
falling revenue; see §9), and those last more than a year. Two limits: MF
ranks were not tested with staler data (stale EBIT can rank a fading
business too high, which is why the EDGAR patch refreshes names older than
`fundamentals.stale_days`), and single names can still flip. In 2026Q3 MOH
passed on its FY2025 row but failed interest cover and loss year on
trailing-twelve-month EDGAR data (`refresh/edgar_ttm_check.py`). Practical
rule: refresh Compustat about twice a year, and use the EDGAR TTM check to
guard the names actually bought. No production change made; the 90-day lag
is a correctness fix worth adopting with the next screen-history rebuild.
Scripts and outputs were in the session scratchpad (`lag_bt.py`).
