"""Report how stale the local Compustat panel is.

Prints the panel's max datadate, per-fyear row counts, and — if a quarter is
given — every HC candidate whose latest fundamentals row is older than the
fundamentals.stale_days threshold. Refresh procedure: data/compustat/REFRESH.md.

    python refresh/compustat_staleness.py [2026Q2]
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import config, ranks  # noqa: E402


def main() -> None:
    con = duckdb.connect(str(config.path("compustat_duckdb")), read_only=True)
    mx, n = con.execute("SELECT max(datadate), count(*) FROM compustat").fetchone()
    recent = con.execute(
        "SELECT fyear, count(*) FROM compustat GROUP BY 1 ORDER BY 1 DESC LIMIT 4").fetchall()
    age = (pd.Timestamp.today() - pd.Timestamp(mx)).days
    print(f"compustat: {n:,} rows, max datadate {mx} ({age} days ago)")
    for fy, cnt in recent:
        print(f"  fyear {fy}: {cnt:,} rows")
    if age > 120:
        print("WARNING: panel likely missing a WRDS refresh — see data/compustat/REFRESH.md")

    if len(sys.argv) > 1:
        q = sys.argv[1]
        cut = ranks.formation_date(q)
        stale_days = config.load()["fundamentals"]["stale_days"]
        df = con.execute(
            "SELECT tic, max(datadate) AS dd FROM compustat "
            "WHERE tic IS NOT NULL GROUP BY 1").df()
        df["age"] = (cut - pd.to_datetime(df["dd"])).dt.days
        stale = df[df["age"] > stale_days]
        print(f"\n{q} (cutoff {cut.date()}): {len(stale):,} tickers stale "
              f"(> {stale_days}d) of {len(df):,} — these get the EDGAR patch "
              f"if they are HC candidates")


if __name__ == "__main__":
    main()
