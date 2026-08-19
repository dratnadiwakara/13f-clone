"""Parameter sweep around the production strategy, judged on robustness.

Grid: MF percentile cutoff x top_n x HC conviction threshold x quant screen
on/off. Same engine as run_windows.py (DCA $1k/month, buy each quarter's
portfolio, never sell). For each variant, besides raw XIRRs, computes the
XIRR with the variant's two most profitable tickers excluded from selection
(slots backfill, as if those names had never existed) and the worst 3-year
window excess vs SPY — the two robustness measures that exposed the MU
dependence of tight-cutoff variants.

    python backtest/sweep.py

Writes backtest/outputs/sweep.csv, prints top variants by robustness score.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_windows as rw  # noqa: E402
from lib import ranks  # noqa: E402

CUTOFFS = [0.2, 0.3, 0.4, 0.5, None]   # None = no MF filter
TOP_NS = [5, 7, 10, None]              # None = no cap
HC_MINS = [0.03, 0.05, 0.07]
QUANTS = [True, False]

SUB_WINDOWS = [w for w in rw.WINDOWS if not w[0].startswith("FULL")]
FULL15 = ("2015-01-01", "2026-05-29")
FULL18 = ("2018-01-01", "2026-05-29")


def run_window_detail(select, quarters, plut, start, end):
    """rw.run_window plus per-ticker cost/terminal for contribution analysis."""
    positions: dict[str, dict] = {}
    cashflows, invested, cash, n_cash = [], 0.0, 0.0, 0
    for d in rw.buy_dates(start, end):
        q = rw.current_quarter(d, quarters)
        tix = select(q) if q else []
        usable = []
        for t in tix:
            yt = t.replace(".", "-")
            p = rw.buy_price(plut, yt, d)
            if p and p > 0:
                usable.append((yt, p))
        cashflows.append((d, -rw.MONTHLY))
        invested += rw.MONTHLY
        if not usable:
            cash += rw.MONTHLY
            n_cash += 1
            continue
        per = rw.MONTHLY / len(usable)
        for yt, p in usable:
            pos = positions.setdefault(yt, {"shares": 0.0, "cost": 0.0})
            pos["shares"] += per / p
            pos["cost"] += per
    term = cash
    profits = {}
    for yt, v in positions.items():
        s = plut.get(yt)
        onb = s[s.index <= end] if s is not None else None
        val = (float(onb.iloc[-1]) if onb is not None and len(onb) else 0.0) * v["shares"]
        term += val
        profits[yt] = val - v["cost"]
    cashflows.append((end, term))
    return {"invested": invested, "terminal": term,
            "multiple": term / invested if invested else float("nan"),
            "xirr": rw.xirr(cashflows), "n_tickers": len(positions),
            "cash_months": n_cash, "profits": profits}


def make_selector(scr, pct, t2g, hc_min, quant, cutoff, top_n, exclude=()):
    def select(q):
        rows = scr[(scr["quarter"] == q)
                   & (scr["hc_alt_weight"].fillna(0) >= hc_min)]
        if quant:
            rows = rows[rows["passes_quant"]]
        cand = sorted(rows["ticker"].dropna().unique())
        cand = [t for t in cand if t not in exclude]
        if cutoff is None and top_n is None:
            return cand
        # MF percentile needed to filter and/or order
        scored = [(t, pct[q][t2g[q][t]]) for t in cand
                  if t in t2g[q] and t2g[q][t] in pct[q]]
        if cutoff is not None:
            scored = [(t, p) for t, p in scored if p <= cutoff]
        scored.sort(key=lambda x: x[1])
        if top_n is not None:
            scored = scored[:top_n]
        return sorted(t for t, _ in scored)
    return select


def main():
    rw.OUT.mkdir(exist_ok=True)
    scr = rw.load_screen()
    quarters = sorted(scr["quarter"].unique())

    print("building MF ranks per quarter...")
    fund = ranks.load_universe()
    pct = {q: ranks.rank_quarter(fund, q).set_index("gvkey")["mf_pct"].to_dict()
           for q in quarters}
    t2g = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
           for q, g in scr.groupby("quarter")}

    prices = pd.read_parquet(rw.CACHE / "prices.parquet")
    plut = {t: g.set_index("date")["close"].sort_index()
            for t, g in prices.groupby("ticker")}

    spy = {}
    for name, s, e in SUB_WINDOWS:
        spy[name] = rw.run_window(lambda q: ["SPY"], quarters, plut,
                                  pd.Timestamp(s), pd.Timestamp(e))["xirr"]
    spy15 = rw.run_window(lambda q: ["SPY"], quarters, plut,
                          pd.Timestamp(FULL15[0]), pd.Timestamp(FULL15[1]))["xirr"]
    spy18 = rw.run_window(lambda q: ["SPY"], quarters, plut,
                          pd.Timestamp(FULL18[0]), pd.Timestamp(FULL18[1]))["xirr"]

    grid = list(itertools.product(CUTOFFS, TOP_NS, HC_MINS, QUANTS))
    print(f"{len(grid)} variants...")
    rows = []
    for i, (cutoff, top_n, hc_min, quant) in enumerate(grid, 1):
        sel = make_selector(scr, pct, t2g, hc_min, quant, cutoff, top_n)
        full = run_window_detail(sel, quarters, plut,
                                 pd.Timestamp(FULL15[0]), pd.Timestamp(FULL15[1]))
        top2 = sorted(full["profits"], key=full["profits"].get, reverse=True)[:2]
        sel_ex = make_selector(scr, pct, t2g, hc_min, quant, cutoff, top_n,
                               exclude=set(top2))
        ex = rw.run_window(sel_ex, quarters, plut,
                           pd.Timestamp(FULL15[0]), pd.Timestamp(FULL15[1]))
        f18 = rw.run_window(sel, quarters, plut,
                            pd.Timestamp(FULL18[0]), pd.Timestamp(FULL18[1]))
        worst_excess = min(
            rw.run_window(sel, quarters, plut,
                          pd.Timestamp(s), pd.Timestamp(e))["xirr"] - spy[name]
            for name, s, e in SUB_WINDOWS)
        q15 = [q for q in quarters if q >= "2014Q4"]
        avg_names = sum(len(sel(q)) for q in q15) / len(q15)
        score = (ex["xirr"] - spy15) + worst_excess
        rows.append({
            "cutoff": cutoff if cutoff is not None else "",
            "top_n": top_n if top_n is not None else "",
            "hc_min": hc_min, "quant": quant,
            "xirr_full15": full["xirr"], "xirr_full18": f18["xirr"],
            "xirr_ex_top2": ex["xirr"], "excluded": "+".join(top2),
            "worst_window_excess": worst_excess,
            "cash_months": full["cash_months"],
            "avg_names_per_qtr": round(avg_names, 1),
            "n_tickers": full["n_tickers"],
            "robustness_score": score,
        })
        print(f"[{i:3}/{len(grid)}] cut={cutoff} n={top_n} hc={hc_min} "
              f"quant={quant}  full15 {full['xirr']*100:6.2f}%  "
              f"ex2 {ex['xirr']*100:6.2f}% (-{'/'.join(top2)})  "
              f"worst {worst_excess*100:+6.2f}pt")

    df = pd.DataFrame(rows).sort_values("robustness_score", ascending=False)
    df.to_csv(rw.OUT / "sweep.csv", index=False)
    print(f"\nSPY: full15 {spy15*100:.2f}%  full18 {spy18*100:.2f}%")
    print(f"wrote {rw.OUT / 'sweep.csv'}\n\ntop 10 by robustness:")
    cols = ["cutoff", "top_n", "hc_min", "quant", "xirr_full15", "xirr_ex_top2",
            "worst_window_excess", "cash_months", "avg_names_per_qtr",
            "robustness_score"]
    print(df[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
