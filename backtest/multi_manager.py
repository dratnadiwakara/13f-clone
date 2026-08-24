"""Production strategy + a "two managers" corroboration requirement.

Everything else is production: HC >= bands.hc_min_weight (10%) of cumulative
purchases over bands.hc_lookback_qtrs (6), full 11-flag quant screen, price
runup cap, MF percentile ranking, mf.top_n (7), macro mega-cap gate, 20%
sizing cap, DCA $1k/month.

"At least two managers" is ambiguous because HC conviction is measured per
(cik, cusip) — a ticker enters the HC set when ONE manager crosses 10%.
VARIANTS.md notes 288 of 325 HC name-quarters come from a single manager, so
the definition chosen matters a lot. Three arms:

  CONV2   2+ managers each independently cross the 10%/6Q HC bar.
          Strictest. Two people each made it a big position.
  HOLD2   1 manager at HC + >=1 other tracked manager HOLDING the name that
          quarter at any weight. Corroboration, not conviction. Reads the raw
          13F panel (data/13f/13f_holdings_slim.parquet) because
          screen_history.csv contains purchase actions only — no pure-hold
          rows — so this arm cannot be computed from the screen cache alone.
  BUY2    2+ managers made a PURCHASE in the trailing 6Q, regardless of
          whether either crossed 10%. Simultaneous accumulation.

Scored the way VARIANTS.md §8 requires: rolling 3-year excess p10 and win rate
over 101 windows, not FULL XIRR alone (§8 documents FULL XIRR selecting
outright broken variants). Every arm inherits the same ~1.6 pt survivorship
overstatement, so cross-arm comparisons are unaffected.

    python backtest/multi_manager.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_windows as rw  # noqa: E402
from lib import config, holdings, managers, ranks  # noqa: E402

START, END = "2015-01-01", "2026-05-29"
ROLL_YEARS = 3


def hc_manager_counts(scr, hc_col, hc_min):
    """(quarter, ticker) -> number of managers at or above the HC bar."""
    hit = scr[scr[hc_col].fillna(0) >= hc_min]
    return hit.groupby(["quarter", "ticker"])["cik"].nunique().to_dict()


def buyer_counts(scr, lookback):
    """(quarter, ticker) -> distinct managers who bought in the trailing N Q.

    Counted over the same trailing window as the HC bar so the two rules are
    measured on identical horizons.
    """
    s = scr[scr["incremental_value_thousands"].fillna(0) > 0].copy()
    s["qidx"] = (s["quarter"].str[:4].astype(int) * 4
                 + s["quarter"].str[-1].astype(int) - 1)
    rows = s[["qidx", "ticker", "cik"]].drop_duplicates()
    all_q = sorted(s["qidx"].unique())
    out = {}
    for q in all_q:
        win = rows[(rows["qidx"] >= q - (lookback - 1)) & (rows["qidx"] <= q)]
        qs = f"{q // 4}Q{q % 4 + 1}"
        for t, n in win.groupby("ticker")["cik"].nunique().items():
            out[(qs, t)] = int(n)
    return out


def holder_counts(scr):
    """(quarter, ticker) -> managers holding that quarter, any weight.

    From the raw 13F panel, not the screen cache: screen_history.csv only
    carries purchase actions (new/add), so a manager sitting on an untouched
    position is invisible there. Mapped cusip8 -> ticker using the screen
    history's own resolution so the two sources agree on naming.
    """
    # lib.holdings.load_holdings does the real work: amendment dedupe (drop all
    # non-/A rows for a manager-quarter that has an amendment), SH-only,
    # put/call excluded, discretion aggregated. Reimplementing it by hand got
    # the amendment rule wrong, so call it.
    h = holdings.load_holdings(ciks=sorted(managers.load_tier_map().keys()))
    h = h[h["value_thousands"].fillna(0) > 0].copy()
    h["cusip8"] = h["cusip"].astype(str).str.strip().str.zfill(9).str[:8]

    xw = scr.dropna(subset=["ticker", "cusip"]).copy()
    xw["cusip8"] = xw["cusip"].astype(str).str.strip().str.zfill(9).str[:8]
    c2t = dict(zip(xw["cusip8"], xw["ticker"]))
    h["ticker"] = h["cusip8"].map(c2t)
    h = h.dropna(subset=["ticker"])
    return h.groupby(["quarter", "ticker"])["cik"].nunique().to_dict()


def build_prod(scr, pct, t2g, runups, blocks, hc_col, hc_min, cut, max_runup,
               top_n, gate=None):
    """Production PROD selector; `gate(q, ticker) -> bool` applied to the HC set.

    The gate sits BEFORE the price cap and the top_n cut, so surviving names
    backfill the freed slots exactly as the price cap's survivors do.
    """
    def select(q):
        rows = scr[(scr["quarter"] == q)
                   & (scr[hc_col].fillna(0) >= hc_min)
                   & scr["passes_quant"]]
        cand = sorted(rows["ticker"].dropna().unique())
        if gate is not None:
            cand = [t for t in cand if gate(q, t)]
        if max_runup is not None:
            cand = [t for t in cand
                    if runups.get((q, t)) is None or runups[(q, t)] <= max_runup]
        scored = [(t, pct[q][t2g[q][t]]) for t in cand
                  if t in t2g[q] and t2g[q][t] in pct[q]
                  and (cut is None or pct[q][t2g[q][t]] <= cut)]
        top = [t for t, _ in sorted(scored, key=lambda x: x[1])[:top_n]]
        blk = blocks.get(q, ())
        return sorted(t for t in top if t not in blk)
    return select


def rolling_excess(sel, quarters, plut, spy_cache, max_w):
    out = []
    starts = pd.date_range(START,
                           pd.Timestamp(END) - pd.DateOffset(years=ROLL_YEARS),
                           freq="MS")
    for s in starts:
        e = s + pd.DateOffset(years=ROLL_YEARS)
        if (s, e) not in spy_cache:
            spy_cache[(s, e)] = rw.run_window(lambda q: ["SPY"], quarters,
                                              plut, s, e)["xirr"]
        r = rw.run_window(sel, quarters, plut, s, e, max_w=max_w)["xirr"]
        if r is not None and spy_cache[(s, e)] is not None:
            out.append(r - spy_cache[(s, e)])
    return np.array(out, dtype=float)


def main():
    rw.OUT.mkdir(exist_ok=True)
    cfg = config.load()
    hc_min = cfg["bands"]["hc_min_weight"]
    lb = cfg["bands"].get("hc_lookback_qtrs", 4)
    hc_col = f"hc_{lb}q"
    cut = cfg["mf"].get("pctile_cutoff")
    top_n = cfg["mf"]["top_n"]
    max_runup = cfg.get("price_cap", {}).get("max_runup")
    max_w = cfg["sizing"]["max_weight"]

    scr = rw.load_screen()
    quarters = sorted(scr["quarter"].unique())

    prices = pd.read_parquet(rw.CACHE / "prices.parquet")
    plut = {t: g.set_index("date")["close"].sort_index()
            for t, g in prices.groupby("ticker")}

    print("building MF ranks per quarter...")
    fund = ranks.load_universe()
    pct = {q: ranks.rank_quarter(fund, q).set_index("gvkey")["mf_pct"].to_dict()
           for q in quarters}
    t2g = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
           for q, g in scr.groupby("quarter")}
    blocks = rw.macro_blocks(scr, fund, plut, quarters)
    runups = rw.price_runups(scr, plut, hc_col, hc_min)

    conv = hc_manager_counts(scr, hc_col, hc_min)
    buys = buyer_counts(scr, lb)
    holds = holder_counts(scr)
    print(f"[counts] HC-conviction pairs {len(conv):,}  "
          f"buyer pairs {len(buys):,}  holder pairs {len(holds):,}")

    ARMS = {
        "PROD (1 manager)": None,
        "CONV2 (2+ at HC)": lambda q, t: conv.get((q, t), 0) >= 2,
        "HOLD2 (HC + 1 holder)": lambda q, t: holds.get((q, t), 0) >= 2,
        "BUY2 (2+ buyers 6Q)": lambda q, t: buys.get((q, t), 0) >= 2,
    }

    spy_cache: dict = {}
    spy_full = rw.run_window(lambda q: ["SPY"], quarters, plut,
                             pd.Timestamp(START), pd.Timestamp(END))["xirr"]
    rows, picks = [], {}
    for name, gate in ARMS.items():
        sel = build_prod(scr, pct, t2g, runups, blocks, hc_col, hc_min, cut,
                         max_runup, top_n, gate=gate)
        full = rw.run_window(sel, quarters, plut, pd.Timestamp(START),
                             pd.Timestamp(END), max_w=max_w)
        roll = rolling_excess(sel, quarters, plut, spy_cache, max_w)
        per_q = {q: sel(q) for q in quarters}
        picks[name] = per_q
        sizes = [len(v) for q, v in per_q.items() if q >= "2014Q4"]
        empty = sum(1 for s in sizes if s == 0)
        rows.append({
            "arm": name,
            "xirr_full": full["xirr"],
            "excess_full": full["xirr"] - spy_full,
            "n_tickers": full["n_tickers"],
            "cash_months": full["cash_months"],
            "avg_names_per_qtr": float(np.mean(sizes)) if sizes else 0.0,
            "empty_quarters": empty,
            "roll_p10": float(np.percentile(roll, 10)) if len(roll) else np.nan,
            "roll_median": float(np.median(roll)) if len(roll) else np.nan,
            "roll_winrate": float((roll > 0).mean()) if len(roll) else np.nan,
        })
        r = rows[-1]
        print(f"{name:24} FULL {r['xirr_full']*100:6.2f}%  "
              f"exc {r['excess_full']*100:+6.2f}  "
              f"p10 {r['roll_p10']*100:+6.2f}  "
              f"med {r['roll_median']*100:+6.2f}  "
              f"win {r['roll_winrate']:5.1%}  "
              f"names/q {r['avg_names_per_qtr']:4.1f}  "
              f"empty {r['empty_quarters']:2d}  cash {r['cash_months']}",
              flush=True)

    df = pd.DataFrame(rows)
    p = rw.OUT / "multi_manager.csv"
    df.to_csv(p, index=False)
    print(f"\nwrote {p}")

    base = picks["PROD (1 manager)"]
    print("\nnames dropped vs production, recent quarters:")
    for q in [q for q in quarters if q >= "2024Q1"]:
        for name in ARMS:
            if name.startswith("PROD"):
                continue
            gone = sorted(set(base[q]) - set(picks[name][q]))
            if gone:
                print(f"  {q} {name:24} -{','.join(gone)}")


if __name__ == "__main__":
    main()
