"""Parameter sweep around the production strategy, judged on robustness.

Grid: MF percentile cutoff x top_n x HC conviction threshold x HC lookback
(quarters of cumulative purchases) x quant screen on/off. Same engine as
run_windows.py (DCA $1k/month, buy each quarter's portfolio, never sell).
For each variant, besides raw XIRRs, computes the XIRR with the variant's
two most profitable tickers excluded from selection (slots backfill, as if
those names had never existed) and the worst 3-year window excess vs SPY —
the two robustness measures that exposed the MU dependence of tight-cutoff
variants.

The macro mega-cap gate (lib/macro: when S&P trailing PE > threshold, block
selections with market cap > 5% of US GDP, no backfill) is applied to every
variant, so the sweep judges the rule set production actually runs. PIT cap
is Compustat prcc_f*csho at the fiscal datadate, rolled forward to the
formation date by price return; S&P PE data starts 2017-01, so the gate is
dormant for pre-2017 quarters.

    python backtest/sweep.py

Writes backtest/outputs/sweep.csv, prints top variants by robustness score.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_windows as rw  # noqa: E402
from lib import config, macro, ranks  # noqa: E402

CUTOFFS = [0.2, 0.3, 0.4, 0.5, None]   # None = no MF filter
TOP_NS = [5, 7, 10, None]              # None = no cap
HC_MINS = [0.03, 0.05, 0.07, 0.10]
LOOKBACKS = [1, 2, 4, 6]               # quarters of cumulative purchases
QUANTS = [True, False]

SUB_WINDOWS = [w for w in rw.WINDOWS if not w[0].startswith("FULL")]
FULL15 = ("2015-01-01", "2026-05-29")
FULL18 = ("2018-01-01", "2026-05-29")


def add_lookback_cols(scr: pd.DataFrame) -> pd.DataFrame:
    """hc_{k}q = purchases summed over trailing k quarters / current portfolio,
    per (cik, cusip) — same window logic as lib/bands.add_hc_alt, whose
    hc_alt_weight is the k=4 case (asserted below)."""
    scr = scr.copy()
    scr["cik"] = scr["cik"].astype(str).str.zfill(10)
    scr["qidx"] = (scr["quarter"].str[:4].astype(int) * 4
                   + scr["quarter"].str[-1].astype(int) - 1)
    cum = {k: np.zeros(len(scr)) for k in LOOKBACKS}
    fill, order = {k: 0 for k in LOOKBACKS}, []
    for _, g in scr.groupby(["cik", "cusip"], sort=False):
        g = g.sort_values("qidx")
        qi = g["qidx"].to_numpy()
        inc = g["incremental_value_thousands"].fillna(0).to_numpy()
        order.append(g.index.to_numpy())
        for k in LOOKBACKS:
            v = np.array([inc[(qi >= q - (k - 1)) & (qi <= q)].sum() for q in qi])
            cum[k][fill[k]:fill[k] + len(g)] = v
            fill[k] += len(g)
    idx = np.concatenate(order)
    for k in LOOKBACKS:
        col = pd.Series(cum[k], index=idx).reindex(scr.index)
        scr[f"hc_{k}q"] = col / scr["portfolio_value_thousands"]
    if 4 in LOOKBACKS:
        d = (scr["hc_4q"] - scr["hc_alt_weight"]).abs().max()
        assert d < 1e-9, f"hc_4q disagrees with shipped hc_alt_weight ({d:.2e})"
    return scr


def build_macro_blocks(scr, fund, plut, quarters) -> dict[str, set]:
    """{quarter: tickers blocked by the macro mega-cap gate}. Empty set when
    the gate is dormant (S&P PE <= threshold, or PE/GDP data missing)."""
    cfg = config.load()["macro"]
    pe_cut, cap_frac = cfg["sp500_pe_threshold"], cfg["mktcap_over_gdp_threshold"]
    t2g_all = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
               for q, g in scr.groupby("quarter")}

    def px(t, d):
        s = plut.get(t.replace(".", "-"))
        if s is None or s.empty:
            return None
        s2 = s[s.index <= d]
        return float(s2.iloc[-1]) if len(s2) else None

    blocks, n_active = {}, 0
    for q in quarters:
        f = ranks.formation_date(q)
        gdp_bn, sp_pe = macro.macro_at(f)
        if not (sp_pe > pe_cut) or gdp_bn != gdp_bn:   # NaN-safe: gate dormant
            blocks[q] = set()
            continue
        n_active += 1
        thr_bn = cap_frac * gdp_bn
        rk = ranks.rank_quarter(fund, q).set_index("gvkey")
        blocked = set()
        for t, g in t2g_all.get(q, {}).items():
            if g not in rk.index:
                continue
            row = rk.loc[g]
            cap_m = float(row["mkt_cap"])
            p_now, p_then = px(t, f), px(t, pd.Timestamp(row["datadate"]))
            if p_now and p_then and p_then > 0:
                cap_m *= p_now / p_then        # roll forward to formation date
            if cap_m / 1000.0 > thr_bn:
                blocked.add(t)
        blocks[q] = blocked
    ever = len({t for s in blocks.values() for t in s})
    print(f"macro gate: active in {n_active}/{len(quarters)} quarters, "
          f"{ever} distinct tickers ever blocked")
    return blocks


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


def make_selector(scr, pct, t2g, hc_min, quant, cutoff, top_n, exclude=(),
                  hc_col="hc_alt_weight", macro_blocks=None):
    def blocked(q):
        return macro_blocks.get(q, ()) if macro_blocks else ()

    def select(q):
        rows = scr[(scr["quarter"] == q)
                   & (scr[hc_col].fillna(0) >= hc_min)]
        if quant:
            rows = rows[rows["passes_quant"]]
        cand = sorted(rows["ticker"].dropna().unique())
        cand = [t for t in cand if t not in exclude]
        if cutoff is None and top_n is None:
            return [t for t in cand if t not in blocked(q)]
        # MF percentile needed to filter and/or order
        scored = [(t, pct[q][t2g[q][t]]) for t in cand
                  if t in t2g[q] and t2g[q][t] in pct[q]]
        if cutoff is not None:
            scored = [(t, p) for t, p in scored if p <= cutoff]
        scored.sort(key=lambda x: x[1])
        if top_n is not None:
            scored = scored[:top_n]
        # macro gate applies AFTER the top_n cut, so blocked slots are not
        # backfilled by the next-best name (matches run_quarter.py)
        return sorted(t for t, _ in scored if t not in blocked(q))
    return select


def main():
    rw.OUT.mkdir(exist_ok=True)
    scr = rw.load_screen()
    scr = add_lookback_cols(scr)
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

    macro_blocks = build_macro_blocks(scr, fund, plut, quarters)

    spy = {}
    for name, s, e in SUB_WINDOWS:
        spy[name] = rw.run_window(lambda q: ["SPY"], quarters, plut,
                                  pd.Timestamp(s), pd.Timestamp(e))["xirr"]
    spy15 = rw.run_window(lambda q: ["SPY"], quarters, plut,
                          pd.Timestamp(FULL15[0]), pd.Timestamp(FULL15[1]))["xirr"]
    spy18 = rw.run_window(lambda q: ["SPY"], quarters, plut,
                          pd.Timestamp(FULL18[0]), pd.Timestamp(FULL18[1]))["xirr"]

    grid = list(itertools.product(CUTOFFS, TOP_NS, HC_MINS, LOOKBACKS, QUANTS))
    print(f"{len(grid)} variants...")
    rows = []
    for i, (cutoff, top_n, hc_min, lb, quant) in enumerate(grid, 1):
        kw = {"hc_col": f"hc_{lb}q", "macro_blocks": macro_blocks}
        sel = make_selector(scr, pct, t2g, hc_min, quant, cutoff, top_n, **kw)
        full = run_window_detail(sel, quarters, plut,
                                 pd.Timestamp(FULL15[0]), pd.Timestamp(FULL15[1]))
        top2 = sorted(full["profits"], key=full["profits"].get, reverse=True)[:2]
        sel_ex = make_selector(scr, pct, t2g, hc_min, quant, cutoff, top_n,
                               exclude=set(top2), **kw)
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
            "hc_min": hc_min, "lookback_qtrs": lb, "quant": quant,
            "xirr_full15": full["xirr"], "xirr_full18": f18["xirr"],
            "xirr_ex_top2": ex["xirr"], "excluded": "+".join(top2),
            "worst_window_excess": worst_excess,
            "cash_months": full["cash_months"],
            "avg_names_per_qtr": round(avg_names, 1),
            "n_tickers": full["n_tickers"],
            "robustness_score": score,
        })
        print(f"[{i:3}/{len(grid)}] cut={cutoff} n={top_n} hc={hc_min} "
              f"lb={lb}q quant={quant}  full15 {full['xirr']*100:6.2f}%  "
              f"ex2 {ex['xirr']*100:6.2f}% (-{'/'.join(top2)})  "
              f"worst {worst_excess*100:+6.2f}pt")

    df = pd.DataFrame(rows).sort_values("robustness_score", ascending=False)
    df.to_csv(rw.OUT / "sweep.csv", index=False)
    print(f"\nSPY: full15 {spy15*100:.2f}%  full18 {spy18*100:.2f}%")
    print(f"wrote {rw.OUT / 'sweep.csv'}\n\ntop 10 by robustness:")
    cols = ["cutoff", "top_n", "hc_min", "lookback_qtrs", "quant",
            "xirr_full15", "xirr_ex_top2",
            "worst_window_excess", "cash_months", "avg_names_per_qtr",
            "robustness_score"]
    print(df[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
