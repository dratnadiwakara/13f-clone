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
  which drops some delisted tickers — survivorship pressure is upward.
- Macro-gate PIT market caps use Compustat `prcc_f × csho` at the fiscal
  datadate rolled forward by price return; shares outstanding can be up to
  550 days stale, so names near the threshold could flip.
