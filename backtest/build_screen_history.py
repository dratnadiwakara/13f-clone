"""Rebuild backtest/cache/screen_history.csv from local data (2014Q1+).

Full pipeline over all quarters: holdings -> actions -> ticker resolution ->
fundamentals screen -> hc_alt_weight. Slow (PIT metrics per signal row).
The shipped CSV was seeded from the source repo; rerun this after a 13F or
Compustat refresh to extend it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import bands, data_access as da, holdings as h_mod, managers, screen as s_mod, signals  # noqa: E402

OUT = Path(__file__).resolve().parent / "cache" / "screen_history.csv"
CUTOFF = pd.Timestamp.today().strftime("%Y-%m-%d")
START_Q = "2014Q1"


def main() -> None:
    tm = managers.load_tier_map()
    hd = h_mod.load_holdings(ciks=sorted(tm.keys()))
    print(f"holdings: {len(hd):,} rows {hd.quarter.min()} -> {hd.quarter.max()}")
    actions = signals.build_actions(hd, start_quarter=START_Q)
    comp = da.load_compstat_for_actions(cutoff=CUTOFF)
    cw = da.load_cusip_ticker_pit()
    actions = signals.resolve_tickers(actions, cw, comp)
    actions["manager_name"] = actions["cik"].map(
        h_mod.latest_manager_names(sorted(tm.keys())))
    mp = actions.rename(columns={"shares": "shares_t",
                                 "value_thousands": "value_thousands_t"})
    print(f"actions: {len(mp):,} rows — running screen (slow)...")
    scr = s_mod.run_screen(mp, cutoff=CUTOFF, live_pe=False)
    scr = bands.add_hc_alt(mp, scr)
    scr.to_csv(OUT, index=False)
    print(f"[ok] {OUT} ({len(scr):,} rows, "
          f"{scr['quarter'].min()} -> {scr['quarter'].max()})")


if __name__ == "__main__":
    main()
