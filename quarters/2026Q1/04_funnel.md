# 2026Q1 — HC ∩ Magic Formula funnel

- Data mode: **BULK**
- Cutoff: 2026-05-20
- HC rule: >= 10% bought over trailing 6Q
- MF: rank-only (no pctile filter), top 7
- Price cap: drop runup > +100% since first buy
- MF universe ranked: 4,006 names
- Macro: S&P PE 29.7, gate ACTIVE (block > $1,593bn cap)

## Portfolio (4 names)

**AZN**, **APP**, **AGYS**, **SPOT**

## Funnel — every HC name

| Ticker | Conviction | Quant | MF pctile | Runup | EDGAR | Outcome |
|---|---|---|---|---|---|---|
| HGV | 11.7% | FAIL | 0.238 | +25% |  | CUT: quant (pass_intcov,pass_leverage,pass_maturity_cliff,pass_quality_gate) |
| AZN | 67.3% | PASS | 0.260 | -5% |  | SELECTED |
| MSFT | 15.3% | PASS | 0.300 | +14% | Y | BLOCKED: macro (mkt_cap_bn=3116>1593_5pct_gdp) |
| APP | 10.0% | PASS | 0.377 | +21% |  | SELECTED |
| TSM | 11.7% | PASS | 0.404 | +107% |  | CUT: price (runup +107% since 2024Q4 > +100%) |
| GOOGL | 11.9% | PASS | 0.412 | +152% |  | CUT: price (runup +152% since 2025Q1 > +100%) |
| AGYS | 12.1% | PASS | 0.421 | +12% | Y | SELECTED |
| SPOT | 11.7% | PASS | 0.434 | -25% |  | SELECTED |
| AMZN | 18.5% | PASS | 0.498 | +21% |  | BLOCKED: macro (mkt_cap_bn=2881>1593_5pct_gdp) |
| CPNG | 18.9% | FAIL | 0.618 | -34% |  | CUT: quant (pass_clean_earnings) |
| GPGI | 13.3% | FAIL | 0.650 | -6% |  | CUT: quant (pass_loss_year,pass_revenue) |
| BOBS | 34.3% | FAIL | — | +2% |  | CUT: quant (pass_quality_gate) |
| IWF | 10.7% | FAIL | — | +39% |  | CUT: quant (pass_etf_exclude) |
| SGOV | 11.2% | FAIL | — | +1% |  | CUT: quant (pass_etf_exclude) |
| TLN | 12.0% | FAIL | — | +73% |  | CUT: quant (pass_intcov,pass_leverage,pass_loss_year) |

## Detail

### HGV
- Managers: CAS Investment Partners, LLC (11.7%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q1 — runup +25% since 2026Q1
- Failed quant flags: pass_intcov,pass_leverage,pass_maturity_cliff,pass_quality_gate

### AZN
- Managers: INVESTOR AB (67.3%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q1 — runup -5% since 2026Q1
- Failed quant flags: none

### MSFT
- Managers: Pershing Square Capital Management, L.P. (15.3%)
- Fundamentals as of: 2026-06-30 (EDGAR companyfacts)
- First buy in window: 2026Q1 — runup +14% since 2026Q1
- Failed quant flags: none

### APP
- Managers: Dorsey Asset Management, LLC (10.0%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2026Q1 — runup +21% since 2026Q1
- Failed quant flags: none

### TSM
- Managers: Newbrook Capital Advisors LP (11.7%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2024Q4 — runup +107% since 2024Q4 > +100%
- Failed quant flags: none

### GOOGL
- Managers: 3G Capital Partners LP (11.9%); Whale Rock Capital Management LLC (10.2%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q1 — runup +152% since 2025Q1 > +100%
- Failed quant flags: none

### AGYS
- Managers: Nine Ten Capital Management LLC (12.1%)
- Fundamentals as of: 2026-03-31 (EDGAR companyfacts)
- First buy in window: 2025Q1 — runup +12% since 2025Q1
- Failed quant flags: none

### SPOT
- Managers: Atalan Capital Partners, LP (11.7%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q4 — runup -25% since 2025Q4
- Failed quant flags: none

### AMZN
- Managers: Pershing Square Capital Management, L.P. (18.5%); ALTAROCK PARTNERS LP (13.8%); BAUPOST GROUP LLC/MA (13.6%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q2 — runup +21% since 2025Q2
- Failed quant flags: none

### CPNG
- Managers: Columbus Hill Capital Management, L.P. (18.9%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2025Q4 — runup -34% since 2025Q4
- Failed quant flags: pass_clean_earnings

### GPGI
- Managers: Nine Ten Capital Management LLC (13.3%)
- Fundamentals as of: 2025-12-31 (Compustat)
- First buy in window: 2024Q4 — runup -6% since 2024Q4
- Failed quant flags: pass_loss_year,pass_revenue

### BOBS
- Managers: Bain Capital Investors LLC (34.3%)
- Fundamentals as of:  (Compustat)
- First buy in window: 2026Q1 — runup +2% since 2026Q1
- Failed quant flags: pass_quality_gate

### IWF
- Managers: Newbrook Capital Advisors LP (10.7%)
- Fundamentals as of:  (Compustat)
- First buy in window: 2025Q1 — runup +39% since 2025Q1
- Failed quant flags: pass_etf_exclude

### SGOV
- Managers: GREENLEA LANE CAPITAL MANAGEMENT, LLC (11.2%)
- Fundamentals as of:  (Compustat)
- First buy in window: 2026Q1 — runup +1% since 2026Q1
- Failed quant flags: pass_etf_exclude

### TLN
- Managers: Sachem Head Capital Management LP (12.0%)
- Fundamentals as of:  (Compustat)
- First buy in window: 2025Q1 — runup +73% since 2025Q1
- Failed quant flags: pass_intcov,pass_leverage,pass_loss_year
