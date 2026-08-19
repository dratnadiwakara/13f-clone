"""(Re)build data/compustat/compustat.duckdb from the local staging parquets.

The duckdb holds two VIEWS over data/compustat/staging/fyear=*/data_0.parquet:
  compustat               -- raw WRDS Compustat Fundamentals Annual panel
  compustat_equity_ratios -- derived valuation ratios (SQL ported verbatim
                             from the source empirical-data-construction db)

Views bake ABSOLUTE parquet paths, so re-run this script whenever the repo
moves on disk or after a WRDS refresh adds/replaces staging files.
"""
from __future__ import annotations
from glob import glob
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "compustat" / "staging"
DB = REPO / "data" / "compustat" / "compustat.duckdb"

EQUITY_RATIOS_SQL = """
CREATE OR REPLACE VIEW compustat_equity_ratios AS
WITH base AS (
  SELECT lpad(gvkey, 6, '0') AS gvkey, datadate,
         CAST((datadate + CAST('90 days' AS INTERVAL)) AS TIMESTAMP) AS public_date,
         fyear, tic, csho, prcc_f, mkvalt, ni, ib, spi, nopi, xido, epspx, epsfx,
         ebit, ebitda, oibdp, dltt, dlc, mib, che, "at", dvc, revt,
         (((ni - COALESCE(spi, 0)) - COALESCE(nopi, 0)) - COALESCE(xido, 0)) AS ni_clean
  FROM compustat
), ratios AS (
  SELECT *,
         CASE WHEN csho > 0 THEN ni_clean / csho ELSE NULL END AS eps_clean,
         COALESCE(ebitda, oibdp) AS ebitda_use,
         (prcc_f * csho) AS mkt_cap,
         CASE WHEN csho > 0 THEN dvc / csho ELSE NULL END AS dps,
         lag(ni_clean, 3) OVER (PARTITION BY gvkey ORDER BY datadate) AS ni_clean_3prior,
         count(ni_clean) OVER (PARTITION BY gvkey ORDER BY datadate
                               ROWS BETWEEN 3 PRECEDING AND CURRENT ROW) AS n_in_window
  FROM base
)
SELECT gvkey, public_date, fyear,
       CASE WHEN eps_clean > 0 AND prcc_f > 0 THEN prcc_f / eps_clean ELSE NULL END AS pe_op_dil,
       CASE WHEN ebitda_use > 0 AND mkt_cap IS NOT NULL
            THEN (mkt_cap + COALESCE(dltt,0) + COALESCE(dlc,0) + COALESCE(mib,0) - COALESCE(che,0)) / ebitda_use
            ELSE NULL END AS evm,
       CASE WHEN dps > 0 AND prcc_f > 0 THEN dps / prcc_f
            WHEN dps = 0 THEN 0.0 ELSE NULL END AS divyield,
       CASE WHEN prcc_f > 0 AND eps_clean > 0 AND n_in_window = 4
                 AND ni_clean_3prior > 0 AND ni_clean > 0
            THEN (prcc_f / eps_clean) / ((power(ni_clean / ni_clean_3prior, 1.0/3.0) - 1) * 100)
            ELSE NULL END AS PEG_trailing,
       CASE WHEN "at" > 0 THEN ni_clean / "at" ELSE NULL END AS roa,
       CASE WHEN ebitda_use > 0
            THEN (COALESCE(dltt,0) + COALESCE(dlc,0) - COALESCE(che,0)) / ebitda_use
            ELSE NULL END AS debt_ebitda,
       tic AS Ticker,
       CAST('t' AS BOOLEAN) AS _synth,
       ni_clean, ni AS ni_raw,
       CASE WHEN ni > 0 THEN ni_clean / ni ELSE NULL END AS ni_clean_pct
FROM ratios
"""


def main() -> None:
    files = sorted(glob(str(STAGING / "fyear=*" / "*.parquet")))
    if not files:
        raise SystemExit(f"no staging parquets under {STAGING}")
    file_list = ", ".join(f"'{f.replace(chr(92), '/')}'" for f in files)
    con = duckdb.connect(str(DB))
    con.execute(
        f"CREATE OR REPLACE VIEW compustat AS SELECT * FROM read_parquet("
        f"[{file_list}], hive_partitioning=true, union_by_name=true)")
    con.execute(EQUITY_RATIOS_SQL)
    n = con.execute("SELECT count(*) FROM compustat").fetchone()[0]
    mx = con.execute("SELECT max(datadate) FROM compustat").fetchone()[0]
    nr = con.execute("SELECT count(*) FROM compustat_equity_ratios").fetchone()[0]
    con.close()
    print(f"{DB}: compustat {n:,} rows (max datadate {mx}), equity_ratios {nr:,} rows, "
          f"{len(files)} staging files")


if __name__ == "__main__":
    main()
