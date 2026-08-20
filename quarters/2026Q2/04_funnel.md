# 2026Q2 — HC ∩ Magic Formula funnel

- Data mode: **PROVISIONAL** (coverage 100%)
- Cutoff: 2026-08-19
- HC rule: >= 10% bought over trailing 6Q
- MF: rank-only (no pctile filter), top 7
- Price cap: drop runup > +100% since first buy
- MF universe ranked: 3,740 names
- Macro: S&P PE 29.6, gate ACTIVE (block > $1,624bn cap)

## Portfolio (6 names)

**PDD**, **BKNG**, **MOH**, **MA**, **APP**, **UNP**

## Funnel — every HC name

| Ticker | Conviction | Quant | MF pctile | Runup | EDGAR | Outcome |
|---|---|---|---|---|---|---|
| DELL | 10.4% | FAIL | 0.069 | +2% |  | CUT: quant (pass_quality_gate) |
| PDD | 25.7% | PASS | 0.097 | -14% |  | SELECTED |
| BKNG | 13.8% | PASS | 0.169 | +17% |  | SELECTED |
| MOH | 12.4% | PASS | 0.172 | -12% |  | SELECTED |
| MA | 14.0% | PASS | 0.240 | +6% |  | SELECTED |
| WHR | 11.2% | FAIL | 0.301 | -48% |  | CUT: quant (pass_leverage,pass_maturity_cliff,pass_quality_gate,pass_revenue) |
| APP | 12.1% | PASS | 0.381 | -22% |  | SELECTED |
| STX | 12.1% | FAIL | 0.383 | +893% | Y | CUT: quant (pass_revenue) |
| MSFT | 10.2% | PASS | 0.386 | +30% |  | BLOCKED: macro (mkt_cap_bn=3586>1624_5pct_gdp) |
| UNP | 11.2% | PASS | 0.429 | +30% |  | SELECTED |
| CVNA | 13.9% | PASS | 0.498 | +68% |  | CUT: rank > top 7 |
| SNPS | 12.5% | FAIL | 0.534 | -10% |  | CUT: quant (pass_clean_earnings,pass_leverage,pass_quality_gate) |
| IWF | 12.2% | FAIL | — | +37% |  | CUT: quant (pass_etf_exclude) |
| KLRA | 12.0% | FAIL | — | -17% |  | CUT: quant (pass_loss_year) |

## Detail

### DELL
- Managers: 3G Capital Partners LP (10.4%)
- Fundamentals as of: 2026-01-31 (Compustat)
- First buy in window: 2026Q2 — runup +2% since 2026Q2
- Failed quant flags: pass_quality_gate

### PDD
- Managers: Himalaya Capital Management LLC (25.7%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q2 — runup -14% since 2025Q2
- Failed quant flags: none

### BKNG
- Managers: Dorsey Asset Management, LLC (13.8%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +17% since 2025Q1
- Failed quant flags: none

### MOH
- Managers: Lingotto Investment Management LLP (12.4%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q2 — runup -12% since 2026Q2
- Failed quant flags: none

### MA
- Managers: Atalan Capital Partners, LP (14.0%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +6% since 2025Q1
- Failed quant flags: none

### WHR
- Managers: RWWM, Inc. (11.2%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q3 — runup -48% since 2025Q3
- Failed quant flags: pass_leverage,pass_maturity_cliff,pass_quality_gate,pass_revenue

### APP
- Managers: Dorsey Asset Management, LLC (12.1%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q1 — runup -22% since 2026Q1
- Failed quant flags: none

### STX
- Managers: Sachem Head Capital Management LP (12.1%)
- Fundamentals as of: 2026-07-03 (EDGAR companyfacts)
- First buy in window: 2025Q1 — runup +893% since 2025Q1 > +100%
- Failed quant flags: pass_revenue

### MSFT
- Managers: ALTAROCK PARTNERS LP (10.2%)
- Fundamentals as of: 2025-06-30 (Compustat)
- First buy in window: 2025Q1 — runup +30% since 2025Q1
- Failed quant flags: none

### UNP
- Managers: Slate Path Capital LP (11.2%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q3 — runup +30% since 2025Q3
- Failed quant flags: none

### CVNA
- Managers: 3G Capital Partners LP (13.9%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +68% since 2025Q1
- Failed quant flags: none

### SNPS
- Managers: Newbrook Capital Advisors LP (12.5%)
- Fundamentals as of: 2025-10-31 (Compustat)
- First buy in window: 2026Q2 — runup -10% since 2026Q2
- Failed quant flags: pass_clean_earnings,pass_leverage,pass_quality_gate

### IWF
- Managers: Newbrook Capital Advisors LP (12.2%)
- Fundamentals as of:  (Compustat)
- First buy in window: 2025Q1 — runup +37% since 2025Q1
- Failed quant flags: pass_etf_exclude

### KLRA
- Managers: Bain Capital Investors LLC (12.0%)
- Fundamentals as of:  (Compustat)
- First buy in window: 2026Q2 — runup -17% since 2026Q2
- Failed quant flags: pass_loss_year
