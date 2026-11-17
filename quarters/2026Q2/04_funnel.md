# 2026Q2 — HC ∩ Magic Formula funnel

- Data mode: **BULK**
- Cutoff: 2026-08-19
- HC rule: >= 10% bought over trailing 6Q
- MF: rank-only (no pctile filter), top 7
- Price cap: drop runup > +100% since first buy
- MF universe ranked: 3,850 names
- Macro: S&P PE 29.6, gate ACTIVE (block > $1,628bn cap)

## Portfolio (7 names)

**PDD**, **MOH**, **BKNG**, **MA**, **UBER**, **META**, **APP**

## Funnel — every HC name

| Ticker | Conviction | Quant | MF pctile | Runup | EDGAR | Outcome |
|---|---|---|---|---|---|---|
| DELL | 10.4% | FAIL | 0.070 | +2% |  | CUT: quant (pass_quality_gate) |
| PDD | 25.7% | PASS | 0.094 | -14% |  | SELECTED |
| MOH | 12.4% | PASS | 0.168 | -12% |  | SELECTED |
| BKNG | 13.8% | PASS | 0.170 | +17% |  | SELECTED |
| MA | 14.0% | PASS | 0.239 | +6% |  | SELECTED |
| UBER | 13.9% | PASS | 0.298 | +7% |  | SELECTED |
| WHR | 11.2% | FAIL | 0.299 | -48% |  | CUT: quant (pass_leverage,pass_maturity_cliff,pass_quality_gate,pass_revenue) |
| META | 11.4% | PASS | 0.354 | -17% |  | SELECTED |
| APP | 12.1% | PASS | 0.379 | -22% |  | SELECTED |
| STX | 12.1% | PASS | 0.382 | +893% | Y | CUT: price (runup +893% since 2025Q1 > +100%) |
| MSFT | 12.7% | PASS | 0.382 | +30% |  | CUT: rank > top 7 |
| UNP | 11.2% | PASS | 0.426 | +30% |  | CUT: rank > top 7 |
| CVNA | 13.9% | PASS | 0.494 | +68% |  | CUT: rank > top 7 |
| AMZN | 15.6% | PASS | 0.502 | +15% |  | CUT: rank > top 7 |
| SNPS | 12.5% | FAIL | 0.528 | -10% |  | CUT: quant (pass_clean_earnings,pass_leverage,pass_quality_gate) |
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

### MOH
- Managers: Lingotto Investment Management LLP (12.4%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q2 — runup -12% since 2026Q2
- Failed quant flags: none

### BKNG
- Managers: Dorsey Asset Management, LLC (13.8%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +17% since 2025Q1
- Failed quant flags: none

### MA
- Managers: Atalan Capital Partners, LP (14.0%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +6% since 2025Q1
- Failed quant flags: none

### UBER
- Managers: PERSHING SQUARE INC. (13.9%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +7% since 2025Q1
- Failed quant flags: none

### WHR
- Managers:  RWWM, INC. (11.2%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q3 — runup -48% since 2025Q3
- Failed quant flags: pass_leverage,pass_maturity_cliff,pass_quality_gate,pass_revenue

### META
- Managers: PERSHING SQUARE INC. (11.4%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q4 — runup -17% since 2025Q4
- Failed quant flags: none

### APP
- Managers: Dorsey Asset Management, LLC (12.1%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q1 — runup -22% since 2026Q1
- Failed quant flags: none

### STX
- Managers: Sachem Head Capital Management LP (12.1%)
- Fundamentals as of: 2026-07-03 (EDGAR companyfacts)
- First buy in window: 2025Q1 — runup +893% since 2025Q1 > +100%
- Failed quant flags: none

### MSFT
- Managers: PERSHING SQUARE INC. (12.7%); ALTAROCK PARTNERS LP (10.2%)
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

### AMZN
- Managers: BAUPOST GROUP LLC/MA (15.6%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q4 — runup +15% since 2025Q4
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
