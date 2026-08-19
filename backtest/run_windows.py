"""Backtest the production strategy per 3-year window + full period.

Strategies:
  SPY   — benchmark
  HC    — conviction >= 5% + quant pass, equal weight
  TOP7  — production rule: HC ∩ quant ∩ MF pctile <= cutoff, top N by pctile

DCA $1,000/month on the 20th, equal weight across the active set, no sells.
Screen history: backtest/cache/screen_history.csv (rebuild with
build_screen_history.py). Prices: backtest/cache/prices.parquet (extend with
fetch_prices.py). MF ranks: computed live from lib/ranks (production universe
rules — foreign financials in, US depositories out).

    python backtest/run_windows.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from scipy.optimize import brentq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import config, ranks  # noqa: E402
from lib.screen import derive_flags  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
OUT = Path(__file__).resolve().parent / "outputs"
MONTHLY = 1000.0

WINDOWS = [
    ("2015-2017", "2015-01-01", "2017-12-29"),
    ("2018-2020", "2018-01-01", "2020-12-31"),
    ("2021-2023", "2021-01-01", "2023-12-29"),
    ("2024-2026H1", "2024-01-01", "2026-05-29"),
    ("FULL 2015-2026", "2015-01-01", "2026-05-29"),
]


# ---------- engine ----------

def xnpv(rate, cf):
    t0 = cf[0][0]
    return sum(c / (1 + rate) ** ((d - t0).days / 365.0) for d, c in cf)


def xirr(cf):
    cfs = sorted(cf, key=lambda x: x[0])
    try:
        return brentq(lambda r: xnpv(r, cfs), -0.99, 10.0, maxiter=200)
    except Exception:
        return float("nan")


def buy_price(plut, yt, d):
    s = plut.get(yt)
    if s is None or s.empty:
        return None
    after = s[s.index >= d]
    if after.empty or (after.index[0] - d).days > 10:
        return None
    return float(after.iloc[0])


def buy_dates(start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    dates, d = [], pd.Timestamp(start.year, start.month, 20)
    while d <= end:
        dates.append(d)
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        d = pd.Timestamp(y, m, 20)
    return dates


def current_quarter(d: pd.Timestamp, quarters: list[str]) -> str | None:
    eligible = [q for q in quarters if ranks.formation_date(q) <= d]
    return max(eligible) if eligible else None


# ---------- data ----------

def load_screen() -> pd.DataFrame:
    scr = pd.read_csv(CACHE / "screen_history.csv",
                      dtype={"quarter": str, "cik": str, "gvkey": str},
                      low_memory=False).dropna(subset=["ticker"])
    scr["gvkey"] = scr["gvkey"].str.zfill(6)
    if "passes_quant" not in scr.columns:
        flags = scr.apply(derive_flags, axis=1, result_type="expand")
        scr = pd.concat([scr, flags.loc[:, ~flags.columns.isin(scr.columns)]], axis=1)
        scr["passes_quant"] = scr[[c for c in scr.columns
                                   if c.startswith("pass_")]].all(axis=1)
    return scr


def build_selectors(scr: pd.DataFrame):
    cfg = config.load()
    hc_min = cfg["bands"]["hc_min_weight"]
    mf = cfg["mf"]
    quarters = sorted(scr["quarter"].unique())

    print("building MF ranks per quarter...")
    fund = ranks.load_universe()
    pct = {q: ranks.rank_quarter(fund, q).set_index("gvkey")["mf_pct"].to_dict()
           for q in quarters}

    t2g = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
           for q, g in scr.groupby("quarter")}

    def hc(q):
        rows = scr[(scr["quarter"] == q)
                   & (scr["hc_alt_weight"].fillna(0) >= hc_min)
                   & scr["passes_quant"]]
        return sorted(rows["ticker"].dropna().unique())

    def top7(q):
        cand = [(t, pct[q][t2g[q][t]]) for t in hc(q)
                if t in t2g[q] and t2g[q][t] in pct[q]
                and pct[q][t2g[q][t]] <= mf["pctile_cutoff"]]
        return sorted(t for t, _ in sorted(cand, key=lambda x: x[1])[:mf["top_n"]])

    return quarters, {"SPY": lambda q: ["SPY"], "HC": hc, "TOP7": top7}


def run_window(select, quarters, plut, start, end, max_w=None) -> dict:
    """max_w: production sizing cap (sizing.max_weight) — per ticker at most
    max_w of the month's deployable money; remainder sits in cash and is
    deployed in later, fuller months. None = uncapped equal weight."""
    positions: dict[str, dict] = {}
    cashflows, invested, cash, n_cash = [], 0.0, 0.0, 0
    for d in buy_dates(start, end):
        q = current_quarter(d, quarters)
        tix = select(q) if q else []
        usable = []
        for t in tix:
            yt = t.replace(".", "-")
            p = buy_price(plut, yt, d)
            if p and p > 0:
                usable.append((yt, p))
        cashflows.append((d, -MONTHLY))
        invested += MONTHLY
        available = cash + MONTHLY
        if not usable:
            cash = available
            n_cash += 1
            continue
        frac = min(1.0 / len(usable), max_w) if max_w else 1.0 / len(usable)
        per = available * frac
        cash = available - per * len(usable)
        for yt, p in usable:
            pos = positions.setdefault(yt, {"shares": 0.0, "cost": 0.0})
            pos["shares"] += per / p
            pos["cost"] += per
    term = cash
    for yt, v in positions.items():
        s = plut.get(yt)
        onb = s[s.index <= end] if s is not None else None
        term += (float(onb.iloc[-1]) if onb is not None and len(onb) else 0.0) * v["shares"]
    cashflows.append((end, term))
    return {"invested": invested, "terminal": term,
            "multiple": term / invested if invested else float("nan"),
            "xirr": xirr(cashflows), "n_tickers": len(positions),
            "cash_months": n_cash}


def main():
    OUT.mkdir(exist_ok=True)
    scr = load_screen()
    quarters, selectors = build_selectors(scr)
    prices = pd.read_parquet(CACHE / "prices.parquet")
    plut = {t: g.set_index("date")["close"].sort_index()
            for t, g in prices.groupby("ticker")}

    max_w = config.load()["sizing"]["max_weight"]
    rows = []
    for name, s, e in WINDOWS:
        for strat, sel in selectors.items():
            # SPY benchmark exempt (single ticker, cap meaningless)
            r = run_window(sel, quarters, plut, pd.Timestamp(s), pd.Timestamp(e),
                           max_w=None if strat == "SPY" else max_w)
            r.update(window=name, strategy=strat)
            rows.append(r)
            print(f"{name:15} {strat:5} XIRR {r['xirr']*100:7.2f}%  "
                  f"mult {r['multiple']:.3f}x  tickers {r['n_tickers']:3}  "
                  f"cash {r['cash_months']}")
    df = pd.DataFrame(rows)[["window", "strategy", "invested", "terminal",
                             "multiple", "xirr", "n_tickers", "cash_months"]]
    df.to_csv(OUT / "windows.csv", index=False)
    print(f"\nwrote {OUT / 'windows.csv'}")


if __name__ == "__main__":
    main()
