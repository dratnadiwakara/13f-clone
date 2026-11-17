# 2026Q3 EDGAR TTM check of the quant screen

Informational. The portfolio uses the Compustat screen. This file re-runs the same flags on trailing-twelve-month EDGAR data (`refresh/edgar_ttm_check.py`; approximations are listed in its docstring). MF ranks are not recomputed.

Names checked: 20. Computed: 16. Pass/fail flips: 2 (AMZN, MOH).

| Ticker | Compustat date | EDGAR TTM date | Compustat | EDGAR | EDGAR fails | Borrowed |
|---|---|---|---|---|---|---|
| AMZN | 2025-12-31 | 2026-09-30 | PASS | FAIL (flip) | pass_clean_earnings |  |
| APP | 2025-12-31 | 2026-09-30 | PASS | PASS |  |  |
| CLS | 2025-12-31 | 2026-09-30 | PASS | PASS |  | revt_cagr_3y |
| HUT | 2025-12-31 | 2026-09-30 | FAIL | FAIL | pass_intcov,pass_loss_year,pass_franchise | revt_cagr_3y |
| MA | 2025-12-31 | 2026-09-30 | PASS | PASS |  | gm_3y |
| MOH | 2025-12-31 | 2026-09-30 | PASS | FAIL (flip) | pass_intcov,pass_loss_year |  |
| MRVL | 2026-01-31 | 2026-08-01 | FAIL | FAIL | pass_clean_earnings,pass_franchise |  |
| PDD | 2025-12-31 | 2025-12-31 | PASS | PASS |  |  |
| PS | | | | | skipped: no TTM revenue/NI could be built | |
| RBLX | 2025-12-31 | 2026-09-30 | FAIL | FAIL | pass_intcov,pass_loss_year |  |
| RIG | 2025-12-31 | 2026-09-30 | FAIL | FAIL | pass_intcov,pass_cash_conversion,pass_franchise |  |
| SKYD | | | | | skipped: no TTM revenue/NI could be built | |
| SLB | 2025-12-31 | 2026-09-30 | PASS | PASS |  | gm_3y |
| SPOT | | | | | skipped: no us-gaap facts (IFRS filer?) | |
| STX | 2026-06-30 | 2026-10-02 | PASS | PASS |  |  |
| TEVA | 2025-12-31 | 2026-09-30 | FAIL | FAIL | pass_leverage,pass_quality_gate |  |
| TSM | | | | | skipped: no us-gaap facts (IFRS filer?) | |
| TTMI | 2025-12-31 | 2026-09-28 | FAIL | FAIL | pass_cash_conversion,pass_quality_gate |  |
| VEEV | 2026-01-31 | 2026-07-31 | PASS | PASS |  |  |
| WHR | 2025-12-31 | 2026-09-30 | FAIL | FAIL | pass_leverage,pass_intcov,pass_loss_year,pass_revenue,pass_quality_gate |  |

## Key metrics (Compustat / EDGAR TTM)

| Ticker | revt_cagr_3y | debt_ebitda | intcov | ni_clean_pct | fcf_to_ni_3y | roic_pre_3y | roic_ex_gdwl | gm_3y |
|---|---|---|---|---|---|---|---|---|
| AMZN | 0.12 / 0.13 | 0.43 / 0.68 | 38.04 / 23.28 | 0.84 / 0.48 | 0.43 / 0.03 | 0.17 / 0.20 | 0.16 / 0.11 | 0.54 / 0.50 |
| APP | 0.22 / 0.36 | 0.27 / 0.06 | 20.19 / 29.80 | 1.04 / 0.96 | 1.36 / 1.11 | 0.63 / 1.04 | 2.05 / 2.35 | 0.84 / 0.93 |
| CLS | 0.20 / 0.20 | 0.26 / -1.86 | 18.68 / 20.70 | 1.04 / 1.00 | 0.71 / 0.48 | 0.29 / 0.43 | 0.41 / 0.47 | 0.12 / 0.12 |
| HUT | 0.11 / 0.11 | -131.97 / 0.29 | -3.48 / -4.04 |  /  | -5.06 / 1.62 | -0.05 / -0.00 | -0.05 / -0.48 | 0.48 / 0.55 |
| MA | 0.14 / 0.14 | 0.41 / 0.61 | 26.87 / 26.19 | 1.01 / 0.98 | 1.10 / 1.07 | 1.09 / 1.05 | 2.39 / 1.77 | 0.62 / 0.62 |
| MOH | 0.12 / 0.10 | -3.94 / -2.13 | 4.55 / 0.81 | 1.20 /  | 0.54 / -0.12 | -2.78 / 0.37 |  / 0.04 | 0.11 / 0.14 |
| MRVL | 0.11 / 0.19 | 0.82 / 0.66 | 6.61 / 7.21 | 0.28 / 0.35 | 4.49 / 2.98 | 0.02 / 0.02 | 0.22 / 0.22 | 0.63 / 0.47 |
| PDD | 0.48 / 0.49 | -5.24 / -1.16 |  /  | 0.73 / 0.97 | 1.19 / 1.20 | -1.12 / 0.40 |  / 0.25 | 0.60 / 0.60 |
| RBLX | 0.30 / 0.31 | 1.24 / 0.09 | -29.73 / -28.11 |  /  | -0.68 / -1.11 | 2.57 / 2.97 |  /  | 0.29 / 0.78 |
| RIG | 0.15 / 0.14 | 3.65 / 3.21 | 1.27 / 1.46 |  / 1.26 | -0.13 / -0.36 | 0.02 / -0.05 | 0.05 / 0.05 | 0.36 / 0.38 |
| SLB | 0.08 / 0.05 | 1.01 / 1.17 | 10.08 / 8.83 | 1.23 / 1.00 | 1.01 / 1.24 | 0.19 / 0.16 | 0.26 / 0.21 | 0.27 / 0.27 |
| STX | 0.18 / 0.27 | 0.49 / 0.19 | 14.88 / 22.30 | 1.08 / 1.00 | 0.92 / 0.87 | 0.53 / 0.70 | 1.16 / 1.43 | 0.38 / 0.39 |
| TEVA | 0.05 / 0.04 | 2.75 / 11.66 | 4.01 /  | 2.23 / 1.00 | -3.48 / 12.23 | 0.16 / 0.05 | 0.56 / 0.13 | 0.56 / 0.51 |
| TTMI | 0.05 / 0.19 | 1.27 / 1.40 | 5.44 / 9.17 | 1.05 / 1.05 | 0.36 / 0.16 | 0.08 / 0.10 | 0.14 / 0.17 | 0.24 / 0.21 |
| VEEV | 0.14 / 0.16 | -6.56 / -1.75 |  /  | 0.73 / 0.71 |  / 1.61 | 0.94 / 0.17 | 2.33 / 0.15 | 0.75 / 0.75 |
| WHR | -0.08 / -0.09 | 6.27 / 7.10 | 2.14 / 1.31 | 0.70 /  | 1.74 / 1.61 | 0.10 / 0.06 | 0.08 / 0.01 | 0.18 / 0.15 |
