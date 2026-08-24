"""top_n sweep for the 4-rule screen, judged the way VARIANTS.md §8 says to.

§10 left one thing open: the 4-rule screen (§9's four survivors) passes 60.2%
of HC candidates versus 39.3% for the full 11-rule screen, so the top_n cut
rather than the screen becomes the binding constraint. top_n was tuned against
the 11-rule pass rate and there is no reason its old value is right for a pool
half again as large. This sweeps top_n against both screens.

Why not backtest/sweep.py: that harness does not implement the price-runup cap
(its own "Known limitations" say so), and it scores on the worst of four fixed
windows — the metric §8 shows understates tail risk (worst fixed window +8.2 pt
versus p10 −6.6 pt over 102 rolling windows). This runs the real PROD path from
run_windows.build_selectors, price cap and macro gate included, and scores on:

  * p10 of rolling 3-year excess vs SPY — §8's recommended risk metric
  * a ticker-drop bootstrap (200 draws, drop 20% of tickers, slots backfill) —
    the measure that justified the one adopted change in the whole log
  * FULL XIRR, reported but NOT used to rank; §8 documents it selecting
    outright broken variants

Every arm inherits the same ~1.6 pt survivorship overstatement (§8), so
comparisons between arms are unaffected.

    python backtest/sweep_topn_4rule.py
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
from lib import config, ranks  # noqa: E402

FOUR = ["pass_loss_year", "pass_intcov", "pass_franchise", "pass_leverage",
        "pass_depository_exclude"]
TOP_NS = [3, 5, 7, 10, 15, None]        # None = no cap
SCREENS = {"4rule": FOUR, "11rule": None}

START, END = "2015-01-01", "2026-05-29"
ROLL_YEARS = 3
N_BOOT = 200
DROP_FRAC = 0.20
BOOT_SEED = 20260823


def build_prod(scr, pct, t2g, runups, blocks, hc_col, hc_min, cut, max_runup,
               top_n, exclude=()):
    """Production PROD selector with top_n parameterised.

    Mirrors run_windows.build_selectors exactly: price cap BEFORE the top_n cut
    so survivors backfill, macro gate AFTER with no backfill.
    """
    def select(q):
        rows = scr[(scr["quarter"] == q)
                   & (scr[hc_col].fillna(0) >= hc_min)
                   & scr["passes_quant"]]
        cand = sorted(rows["ticker"].dropna().unique())
        if exclude:
            cand = [t for t in cand if t not in exclude]
        if max_runup is not None:
            cand = [t for t in cand
                    if runups.get((q, t)) is None or runups[(q, t)] <= max_runup]
        scored = [(t, pct[q][t2g[q][t]]) for t in cand
                  if t in t2g[q] and t2g[q][t] in pct[q]
                  and (cut is None or pct[q][t2g[q][t]] <= cut)]
        top = [t for t, _ in sorted(scored, key=lambda x: x[1])[
            :(top_n if top_n is not None else len(scored))]]
        blk = blocks.get(q, ())
        return sorted(t for t in top if t not in blk)
    return select


def rolling_excess(sel, quarters, plut, spy_cache):
    """Excess vs SPY over every rolling 3y window starting each month.

    §8: 3-year windows are long enough for a no-exit strategy and give 100+
    observations, versus four fixed windows that hid a −14.4 pt worst case.
    """
    out = []
    starts = pd.date_range(START, pd.Timestamp(END) - pd.DateOffset(years=ROLL_YEARS),
                           freq="MS")
    for s in starts:
        e = s + pd.DateOffset(years=ROLL_YEARS)
        key = (s, e)
        if key not in spy_cache:
            spy_cache[key] = rw.run_window(lambda q: ["SPY"], quarters, plut,
                                           s, e)["xirr"]
        r = rw.run_window(sel, quarters, plut, s, e,
                          max_w=config.load()["sizing"]["max_weight"])["xirr"]
        if r is not None and spy_cache[key] is not None:
            out.append(r - spy_cache[key])
    return np.array(out, dtype=float)


def ticker_drop_bootstrap(make_sel, quarters, plut, spy_full, rng):
    """Drop 20% of tickers, let slots backfill, re-run FULL excess.

    Guards against a result resting on two or three names — §8 found dropping
    the top 10 of 210 picks cut mean excess from +9.30 to +2.04 pt.
    """
    universe = sorted({t for q in quarters for t in make_sel(())(q)})
    if not universe:
        return np.array([])
    out = []
    max_w = config.load()["sizing"]["max_weight"]
    for _ in range(N_BOOT):
        k = max(1, int(len(universe) * DROP_FRAC))
        drop = set(rng.choice(universe, size=k, replace=False))
        r = rw.run_window(make_sel(drop), quarters, plut,
                          pd.Timestamp(START), pd.Timestamp(END),
                          max_w=max_w)["xirr"]
        if r is not None:
            out.append(r - spy_full)
    return np.array(out, dtype=float)


def main():
    rw.OUT.mkdir(exist_ok=True)
    cfg = config.load()
    hc_min = cfg["bands"]["hc_min_weight"]
    lookback = cfg["bands"].get("hc_lookback_qtrs", 4)
    hc_col = f"hc_{lookback}q"
    cut = cfg["mf"].get("pctile_cutoff")
    max_runup = cfg.get("price_cap", {}).get("max_runup")
    max_w = cfg["sizing"]["max_weight"]

    prices = pd.read_parquet(rw.CACHE / "prices.parquet")
    plut = {t: g.set_index("date")["close"].sort_index()
            for t, g in prices.groupby("ticker")}

    print("building MF ranks per quarter...")
    fund = ranks.load_universe()

    rows = []
    spy_cache: dict = {}
    for sname, subset in SCREENS.items():
        scr = rw.load_screen(subset)
        quarters = sorted(scr["quarter"].unique())
        pct = {q: ranks.rank_quarter(fund, q).set_index("gvkey")["mf_pct"].to_dict()
               for q in quarters}
        t2g = {q: g.dropna(subset=["gvkey"]).set_index("ticker")["gvkey"].to_dict()
               for q, g in scr.groupby("quarter")}
        blocks = rw.macro_blocks(scr, fund, plut, quarters)
        runups = rw.price_runups(scr, plut, hc_col, hc_min)

        spy_full = rw.run_window(lambda q: ["SPY"], quarters, plut,
                                 pd.Timestamp(START), pd.Timestamp(END))["xirr"]
        pass_rate = scr["passes_quant"].mean()

        for top_n in TOP_NS:
            def mk(exclude=()):
                return build_prod(scr, pct, t2g, runups, blocks, hc_col,
                                  hc_min, cut, max_runup, top_n,
                                  exclude=exclude)
            sel = mk()
            full = rw.run_window(sel, quarters, plut, pd.Timestamp(START),
                                 pd.Timestamp(END), max_w=max_w)
            roll = rolling_excess(sel, quarters, plut, spy_cache)
            rng = np.random.default_rng(BOOT_SEED)
            boot = ticker_drop_bootstrap(mk, quarters, plut, spy_full, rng)
            names = [len(sel(q)) for q in quarters]

            rec = {
                "screen": sname, "top_n": top_n if top_n is not None else -1,
                "pass_rate": pass_rate,
                "xirr_full": full["xirr"],
                "excess_full": full["xirr"] - spy_full,
                "n_tickers": full["n_tickers"],
                "cash_months": full["cash_months"],
                "avg_names_per_qtr": float(np.mean(names)),
                "roll_n": len(roll),
                "roll_p10": float(np.percentile(roll, 10)) if len(roll) else np.nan,
                "roll_median": float(np.median(roll)) if len(roll) else np.nan,
                "roll_winrate": float((roll > 0).mean()) if len(roll) else np.nan,
                "boot_p5": float(np.percentile(boot, 5)) if len(boot) else np.nan,
                "boot_median": float(np.median(boot)) if len(boot) else np.nan,
            }
            rows.append(rec)
            tn = "none" if top_n is None else str(top_n)
            print(f"{sname:7} top_n={tn:>4}  FULL {rec['xirr_full']*100:6.2f}%  "
                  f"exc {rec['excess_full']*100:+6.2f}  "
                  f"roll p10 {rec['roll_p10']*100:+6.2f}  "
                  f"med {rec['roll_median']*100:+6.2f}  "
                  f"win {rec['roll_winrate']:5.1%}  "
                  f"boot p5 {rec['boot_p5']*100:+6.2f}  "
                  f"names/q {rec['avg_names_per_qtr']:4.1f}", flush=True)

    df = pd.DataFrame(rows)
    # Rank on rolling p10 (§8's recommended risk metric), NOT on FULL XIRR.
    df = df.sort_values("roll_p10", ascending=False)
    p = rw.OUT / "sweep_topn_4rule.csv"
    df.to_csv(p, index=False)
    print(f"\nwrote {p}")
    print("\nranked by rolling-3y p10 excess (§8's risk metric):")
    show = ["screen", "top_n", "roll_p10", "roll_median", "roll_winrate",
            "boot_p5", "excess_full", "avg_names_per_qtr"]
    print(df[show].to_string(index=False))


if __name__ == "__main__":
    main()
