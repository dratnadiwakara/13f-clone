---
name: run-quarter
description: Run the quarterly HC ∩ Magic Formula production pipeline for a quarter (e.g. 2026Q3) end to end, which means a 13F coverage check, a Compustat staleness check, run_quarter.py, verification of 04_funnel.md, and the subjective 05_watchlist.md write-up. Use when asked to "run the quarter", "run 2026Q3", "build this quarter's portfolio", or /run-quarter.
---

# Run the quarter

Argument: the quarter as `YYYYQn`. If none is given, use the latest quarter
whose 13F filing deadline (45 days after quarter end) has passed, and say
which quarter you picked.

Run every command from the repo root with PowerShell. Network scripts read
the SEC User-Agent from `SEC_USER_AGENT`, which is set at user level. Load it
into each PowerShell command that touches the network, and never print it:

```
$env:SEC_USER_AGENT = [Environment]::GetEnvironmentVariable('SEC_USER_AGENT','User'); $env:PYTHONIOENCODING = 'utf-8'; <command>
```

If the variable is empty, stop and ask the user to run
`! setx SEC_USER_AGENT "investments-research/1.0 <their email>"`. Do not
hardcode or type an email address anywhere.

## 1. Preflight

1. Read `data/13f/13f_holdings_slim.state.json`. If the quarter is at or
   below `max_quarter`, the run uses bulk data. Skip to step 2.
2. Otherwise check provisional coverage without writing anything:
   `C:\envs\.basic_venv\Scripts\python.exe refresh\fetch_13f_filings.py --quarter Q --dry-run --refresh`
   Report filed/expected. If coverage is below `provisional.min_coverage` in
   `config.yaml` (0.75), stop and tell the user how many managers are still
   missing. The script computes the deadline as day 45 and does not roll a
   weekend to Monday; state the effective deadline yourself.
3. Check Compustat age:
   `C:\envs\.basic_venv\Scripts\python.exe refresh\compustat_staleness.py Q`
   Pass on any warning. A stale panel does not block the run (HC names get
   the EDGAR patch), but the user should know.

## 2. Run

```
C:\envs\.basic_venv\Scripts\python.exe run_quarter.py Q
```

Use a long timeout (up to 10 minutes). Add `--no-refresh` only if the user
asks or the network is down. If the script exits early, report its message
as written and stop. Do not edit `config.yaml` or `lib/` to get a run through.

## 3. Verify

Read `quarters/Q/03_portfolio.txt` and `quarters/Q/04_funnel.md`. Check that:

- the mode (bulk or provisional) and coverage are what preflight found;
- every HC name has a stated selection or cut reason;
- the number of selected names is at most `mf.top_n`, weights are capped at
  `sizing.max_weight`, and any remainder is listed as CASH;
- macro-gate blocks and price-cap drops look consistent with the funnel text.

Flag anything odd (a familiar HC name with no Compustat match, tickers that
look like CUSIP-change artifacts, an empty portfolio). Do not fix it silently.

## 3b. EDGAR TTM check of all HC names

The pipeline screens on annual Compustat rows, which can be 12 to 18 months
old. Re-run the same quant flags on trailing-twelve-month EDGAR data for
every HC name (network, so load `SEC_USER_AGENT` as above):

```
C:\envs\.basic_venv\Scripts\python.exe refresh\edgar_ttm_check.py Q
```

It writes `quarters/Q/07_edgar_check.md` and `.csv`. The check is
informational: it never changes `03_portfolio.txt`, and you must not edit
the portfolio because of it. Read the md and:

- list every flip (Compustat PASS to EDGAR FAIL, or the reverse), with the
  failing flags and the TTM numbers behind them;
- before calling a flip real, look at the raw numbers. Known artifacts: a
  missing XBRL tag set to 0 (for example D&A, so EBITDA equals EBIT and
  leverage looks too high), a filer with no COGS line (gross margin borrowed
  from Compustat, listed under "Borrowed"), short US-GAAP history after an
  IFRS switch;
- name the skipped names (IFRS filers such as TSM or SPOT, funds, no TTM
  data). They keep their Compustat result only.

If a selected name flips to FAIL on real numbers, say so in the report and
leave the decision to the operator (an override goes in `06_override.md`).

## 4. Watchlist

Write `quarters/Q/05_watchlist.md` from `05_watchlist_data.csv` and
`04_funnel.md`, following the "Subjective watchlist" section of `CLAUDE.md`
exactly: 0 to 8 picks, ranked as long-term investments (franchise
durability, then price, then conviction), the required header with today's
date, per-pick buyers and weights, financials, MF percentile, the case, and
what would change it. Name any rows to ignore. Follow the user's writing
rules: plain English, no em dashes, numbers over adjectives.

## 5. Report

Keep it short:

- the portfolio as a table (ticker, weight), plus CASH. If
  `quarters/Q/06_override.md` exists, show the traded list from it and say
  which names the operator changed;
- HC names cut, with a one-line reason each;
- EDGAR TTM check: flips and skipped names from `07_edgar_check.md`, with a
  clear note on any selected name that fails on the latest data;
- the watchlist picks in rank order;
- timing: quarter end date, the filing window the data came from, and
  whether the run is provisional. If provisional, say that the bulk quarter
  will replace it later and the result may change slightly.

Do not commit, and do not merge any provisional sidecar into
`13f_holdings_slim.parquet`.

## 6. Recurring orders and recurring transfers

After every quarterly run, end the report with where to check and change
both in the IBKR Client Portal. Use a web browser: TWS and the mobile app's
standard order screens cannot manage these.

Recurring orders (the new quarter's tickers and weights):
- In the left menu, expand **Trade**, then click **Recurring Investments**.
- Recurring orders are only there. The Orders & Trades page has no
  recurring filter, so do not send the user there.

Recurring transfers (step 1, delete the existing transfer):
- In the top navigation menu, go to **Transfer & Pay > Saved Information**.
- Scroll to the **Recurring Transactions** section.
- Find the recurring transfer, click the **X** (delete) icon next to it,
  and click **Yes** to confirm.
