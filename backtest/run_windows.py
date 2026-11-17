"""Backtest the production strategy per 3-year window + full period.

Strategies:
  SPY   — benchmark
  HC    — conviction >= bands.hc_min_weight + quant pass, equal weight
  PROD  — production rule: HC (>= 10% over trailing 6Q) ∩ quant, ranked by MF
          percentile (rank-only unless mf.pctile_cutoff is set), price-runup
          cap, macro mega-cap gate, top mf.top_n (with macro.backfill the
          gate runs before the cut and survivors fill blocked slots;
          --macro-backfill overrides), 20% sizing cap

DCA $1,000/month on the 20th, equal weight across the active set, no sells.
Screen history: backtest/cache/screen_history.csv (rebuild with
build_screen_history.py). Prices: backtest/cache/prices.parquet (extend with
fetch_prices.py). MF ranks: computed live from lib/ranks (production universe
rules — foreign financials in, US depositories out).

    python backtest/run_windows.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import config, macro, ranks  # noqa: E402
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

def add_hc_windows(scr: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Derive hc_{lookback}q and first_buy_quarter from the raw incremental
    purchase values, so a cache built under a different bands.hc_lookback_qtrs
    still works. Same window logic as lib/bands.add_hc_alt."""
    scr = scr.copy()
    scr["cik"] = scr["cik"].astype(str).str.zfill(10)
    scr["qidx"] = (scr["quarter"].str[:4].astype(int) * 4
                   + scr["quarter"].str[-1].astype(int) - 1)
    cum = np.zeros(len(scr))
    first = np.full(len(scr), np.nan)
    fill, order = 0, []
    for _, g in scr.groupby(["cik", "cusip"], sort=False):
        g = g.sort_values("qidx")
        qi = g["qidx"].to_numpy()
        inc = g["incremental_value_thousands"].fillna(0).to_numpy()
        order.append(g.index.to_numpy())
        for j, q in enumerate(qi):
            win = (qi >= q - (lookback - 1)) & (qi <= q)
            cum[fill + j] = inc[win].sum()
            bought = win & (inc > 0)
            if bought.any():
                first[fill + j] = qi[bought].min()
        fill += len(g)
    idx = np.concatenate(order)
    scr[f"hc_{lookback}q"] = (pd.Series(cum, index=idx).reindex(scr.index)
                              / scr["portfolio_value_thousands"])
    fb = pd.Series(first, index=idx).reindex(scr.index)
    scr["first_buy_quarter"] = fb.map(
        lambda v: None if v != v else f"{int(v) // 4}Q{int(v) % 4 + 1}")
    return scr


def load_screen(flags_subset: list[str] | None = None) -> pd.DataFrame:
    """Screen history with passes_quant.

    flags_subset restricts which pass_* columns are ANDed into passes_quant,
    overriding whatever the cache carries. Used to test a reduced screen — see
    VARIANTS.md §9, where only 4 of the 11 flags survive a size/sector-matched
    disaster-avoidance test on the full Compustat universe. None = production
    behaviour (all flags).
    """
    scr = pd.read_csv(CACHE / "screen_history.csv",
                      dtype={"quarter": str, "cik": str, "gvkey": str},
                      low_memory=False).dropna(subset=["ticker"])
    scr["gvkey"] = scr["gvkey"].str.zfill(6)
    if "passes_quant" not in scr.columns or flags_subset is not None:
        have = [c for c in scr.columns if c.startswith("pass_")]
        if not have:
            flags = scr.apply(derive_flags, axis=1, result_type="expand")
            scr = pd.concat(
                [scr, flags.loc[:, ~flags.columns.isin(scr.columns)]], axis=1)
            have = [c for c in scr.columns if c.startswith("pass_")]
        use = have if flags_subset is None else [c for c in flags_subset]
        missing = [c for c in use if c not in scr.columns]
        if missing:
            raise SystemExit(f"unknown flag column(s): {missing}")
        # A name with no gvkey match never got flags computed; production
        # marks it passes_quant=False in run_screen. Preserve that.
        no_data = scr[use].isna().all(axis=1)
        scr["passes_quant"] = scr[use].fillna(True).all(axis=1) & ~no_data
    return add_hc_windows(scr, config.load()["bands"].get("hc_lookback_qtrs", 4))


def _px(plut, t, d):
    s = plut.get(t.replace(".", "-"))
    if s is None or s.empty:
        return None
    prior = s[s.index <= d]
    return float(prior.iloc[-1]) if len(prior) else None


def macro_blocks(scr, fund, plut, quarters) -> dict[str, set]:
    """{quarter: tickers over the macro mega-cap threshold}. PIT cap is
    Compustat prcc_f*csho at the fiscal datadate, rolled forward to the
    formation date by price return. Empty when the gate is dormant."""
    cfg = config.load()["macro"]
    pe_cut, frac = cfg["sp500_pe_threshold"], cfg["mktcap_over_gdp_threshold"]
    t2g_all = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
               for q, g in scr.groupby("quarter")}
    out = {}
    for q in quarters:
        f = ranks.formation_date(q)
        gdp_bn, sp_pe = macro.macro_at(f)
        if not (sp_pe > pe_cut) or gdp_bn != gdp_bn:     # NaN-safe: dormant
            out[q] = set()
            continue
        thr_bn, rk = frac * gdp_bn, ranks.rank_quarter(fund, q).set_index("gvkey")
        blocked = set()
        for t, g in t2g_all.get(q, {}).items():
            if g not in rk.index:
                continue
            row = rk.loc[g]
            cap_m = float(row["mkt_cap"])
            p_now, p_then = _px(plut, t, f), _px(plut, t, pd.Timestamp(row["datadate"]))
            if p_now and p_then and p_then > 0:
                cap_m *= p_now / p_then
            if cap_m / 1000.0 > thr_bn:
                blocked.add(t)
        out[q] = blocked
    return out


def price_runups(scr, plut, hc_col, hc_min) -> dict:
    """{(quarter, ticker): runup} since the end of the earliest quarter in the
    lookback window where a qualifying manager bought (lib/pricecap's rule).
    Missing from the dict = no usable price history = passes the cap."""
    elig = scr[(scr[hc_col].fillna(0) >= hc_min) & scr["passes_quant"]
               & scr["first_buy_quarter"].notna()]
    out = {}
    for (q, t), g in elig.groupby(["quarter", "ticker"]):
        fq = sorted(g["first_buy_quarter"].dropna())[0]   # earliest across managers
        p_then = _px(plut, t, ranks.quarter_end(fq))
        p_now = _px(plut, t, ranks.formation_date(q))
        if p_then and p_now and p_then > 0:
            out[(q, t)] = p_now / p_then - 1.0
    return out


def build_selectors(scr: pd.DataFrame, plut=None, macro_backfill=None):
    """plut (ticker -> close series) enables the price-runup cap and the macro
    gate; omit it for a bare HC/MF run. macro_backfill None reads
    config macro.backfill."""
    cfg = config.load()
    if macro_backfill is None:
        macro_backfill = cfg["macro"].get("backfill", False)
    hc_min = cfg["bands"]["hc_min_weight"]
    lookback = cfg["bands"].get("hc_lookback_qtrs", 4)
    mf = cfg["mf"]
    cut = mf.get("pctile_cutoff")
    max_runup = cfg.get("price_cap", {}).get("max_runup")
    quarters = sorted(scr["quarter"].unique())

    hc_col = f"hc_{lookback}q"
    print("building MF ranks per quarter...")
    fund = ranks.load_universe()
    pct = {q: ranks.rank_quarter(fund, q).set_index("gvkey")["mf_pct"].to_dict()
           for q in quarters}

    t2g = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
           for q, g in scr.groupby("quarter")}

    blocks = macro_blocks(scr, fund, plut, quarters) if plut is not None else {}
    runups = price_runups(scr, plut, hc_col, hc_min) if plut is not None else {}

    def hc(q):
        rows = scr[(scr["quarter"] == q)
                   & (scr[hc_col].fillna(0) >= hc_min)
                   & scr["passes_quant"]]
        return sorted(rows["ticker"].dropna().unique())

    def prod(q):
        cand = hc(q)
        if max_runup is not None:            # price cap, before the top_n cut
            cand = [t for t in cand
                    if runups.get((q, t)) is None or runups[(q, t)] <= max_runup]
        scored = [(t, pct[q][t2g[q][t]]) for t in cand
                  if t in t2g[q] and t2g[q][t] in pct[q]
                  and (cut is None or pct[q][t2g[q][t]] <= cut)]
        blk = blocks.get(q, ())              # macro gate
        ranked = [t for t, _ in sorted(scored, key=lambda x: x[1])]
        if macro_backfill:                   # before the cut: survivors backfill
            return sorted([t for t in ranked if t not in blk][:mf["top_n"]])
        return sorted(t for t in ranked[:mf["top_n"]] if t not in blk)

    return quarters, {"SPY": lambda q: ["SPY"], "HC": hc, "PROD": prod}


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--flags", default=None,
                    help="comma-separated pass_* subset to AND into "
                         "passes_quant (default: all flags in the cache)")
    ap.add_argument("--out", default="windows.csv")
    ap.add_argument("--macro-backfill", choices=["on", "off"], default=None,
                    help="override config macro.backfill")
    args = ap.parse_args()
    subset = ([f.strip() for f in args.flags.split(",")]
              if args.flags else None)
    if subset:
        print(f"[screen] restricted to {len(subset)} flags: {', '.join(subset)}")

    OUT.mkdir(exist_ok=True)
    scr = load_screen(subset)
    prices = pd.read_parquet(CACHE / "prices.parquet")
    plut = {t: g.set_index("date")["close"].sort_index()
            for t, g in prices.groupby("ticker")}
    mb = None if args.macro_backfill is None else args.macro_backfill == "on"
    quarters, selectors = build_selectors(scr, plut=plut, macro_backfill=mb)

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
    df.to_csv(OUT / args.out, index=False)
    print(f"\nwrote {OUT / args.out}")


if __name__ == "__main__":
    main()
