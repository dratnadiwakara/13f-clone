# Compustat refresh procedure (manual, WRDS)

The panel is WRDS Compustat Fundamentals Annual (`comp.funda`) and cannot be
auto-refreshed from EDGAR. The pipeline tolerates staleness: annual data is
used with a 90-day lag anyway, and HC candidates with a newer 10-K on EDGAR
get patched at run time (`refresh/refresh_fundamentals.py`). Refresh the
panel about twice a year, or when `refresh/compustat_staleness.py` warns.

How much staleness matters was tested in `backtest/VARIANTS.md` §15: running
the quant screen on reports at least a year old moved FULL XIRR by −0.5 pt
(inside the noise floor). A late refresh costs little at the portfolio
level. Single names can still change, so `refresh/edgar_ttm_check.py`
re-screens every HC name on trailing-twelve-month EDGAR data each quarter.

1. On WRDS, export Compustat North America Fundamentals Annual
   (`comp.funda`), standard filters (INDL+FS, consolidated, domestic+intl),
   all variables, one file per fiscal year (or one file split afterward).
2. Write each fiscal year to `staging/fyear=YYYY/data_0.parquet`
   (columns as-is from WRDS; the views use `union_by_name`).
3. Rebuild the duckdb views:
   `C:\envs\.basic_venv\Scripts\python.exe refresh\build_compustat_db.py`
4. Sanity: `refresh\compustat_staleness.py` should show the new max datadate.

Note: the duckdb stores ABSOLUTE staging paths — re-run step 3 whenever the
repo moves on disk.
