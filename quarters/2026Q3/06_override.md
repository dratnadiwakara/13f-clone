# 2026Q3 operator override

Recorded 2026-11-16. This is a manual change by the operator. It is not produced by `run_quarter.py`, and a rerun of the pipeline will not reflect it.

**Change:** replace MOH with VEEV for this quarter only.

**Reason:** MOH is already in the portfolio from the 2026Q2 buys, which are held and not sold. Using this quarter's slot for VEEV adds a new exposure instead of adding more to an existing one.

| Ticker | Pipeline (`03_portfolio.txt`) | Traded |
|---|---|---|
| PDD | 14.3% | 14.3% |
| SLB | 14.3% | 14.3% |
| MOH | 14.3% | removed |
| VEEV | not selected | 14.3% |
| MA | 14.3% | 14.3% |
| APP | 14.3% | 14.3% |
| STX | 14.3% | 14.3% |
| CLS | 14.3% | 14.3% |

**Context from the funnel:**
- VEEV is an HC name (Dorsey, new position at 14.1%) and passes every screen. It ranks at mf 0.530 and was cut only by the top 7 limit. Its price is up 5% since Dorsey's first buy.
- SPOT (10.4%, mf 0.437) ranks ahead of VEEV and would be the next name under a mechanical "skip held, take next-ranked" rule. The operator chose VEEV over SPOT.
- MOH is an HC name (Lingotto, 11.7%) at mf 0.172 and passes every screen. Lingotto added 20% more shares this quarter.
- A scratchpad backtest of a general "skip names already held" rule (2026-11-16) lowered FULL XIRR by 0.7 to 0.9 pt, below the 2.6 pt noise floor. That is why this stays a one-quarter judgment, not a rule.

Revisit this override when the 2026Q4 run is done. It does not carry forward.
