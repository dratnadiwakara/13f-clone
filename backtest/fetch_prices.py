"""Extend backtest/cache/prices.parquet with yfinance daily adjusted closes.

Fetches any ticker in screen_history.csv (plus SPY) not already cached,
from 2014-12-01 to today. Incremental: cached tickers are skipped.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE = Path(__file__).resolve().parent / "cache"
PQ = CACHE / "prices.parquet"


def main() -> None:
    scr = pd.read_csv(CACHE / "screen_history.csv", dtype={"quarter": str},
                      low_memory=False)
    tics = sorted({str(t).replace(".", "-")
                   for t in scr["ticker"].dropna().unique()} | {"SPY"})
    frames, done = [], set()
    if PQ.exists():
        prev = pd.read_parquet(PQ)
        done = set(prev["ticker"].unique())
        frames.append(prev)
    todo = [t for t in tics if t not in done]
    print(f"{len(tics)} tickers, {len(todo)} to fetch")
    end = (pd.Timestamp.today() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    for i in range(0, len(todo), 100):
        ch = todo[i:i + 100]
        print(f"chunk {i // 100 + 1}/{(len(todo) + 99) // 100}")
        df = yf.download(ch, start="2014-12-01", end=end, auto_adjust=True,
                         group_by="ticker", progress=False, threads=True)
        for t in ch:
            try:
                s = df[t]["Close"] if len(ch) > 1 else df["Close"]
            except (KeyError, ValueError):
                continue
            s = s.dropna()
            if not s.empty:
                frames.append(pd.DataFrame(
                    {"date": s.index, "ticker": t, "close": s.values}))
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.tz_localize(None)
    out.to_parquet(PQ, index=False)
    print(f"done: {out['ticker'].nunique()} tickers cached")


if __name__ == "__main__":
    main()
