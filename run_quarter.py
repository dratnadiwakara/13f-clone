"""Quarterly strategy run.

    python run_quarter.py 2026Q1 [--no-refresh]

Pipeline: 13F freshness (bulk append, else provisional at >=75% manager
coverage) -> HC set (trailing-4Q conviction >= 5%) -> EDGAR fundamentals patch
for stale names -> quant screen -> global magic-formula percentile -> keep
<= 40%, top 7 by percentile -> macro mega-cap gate.

Outputs to quarters/{Q}/: 01_screen.csv, 02_ranks.parquet, 03_portfolio.txt,
04_funnel.md. The funnel lists every HC name with the exact reason it was
selected or cut.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from lib import (  # noqa: E402
    bands, config, data_access as da, holdings as h_mod,
    macro, managers, ranks, screen as s_mod, signals,
)
from lib.screen import derive_flags  # noqa: E402

PY = sys.executable


# ---------- 13F freshness ----------

def ensure_13f(q: str, no_refresh: bool) -> tuple[str, float | None]:
    """Return (mode, coverage): mode in {'bulk', 'provisional'}. Exits if the
    quarter is unavailable in either form (or coverage < threshold)."""
    state = json.loads((REPO / "data/13f/13f_holdings_slim.state.json").read_text())
    if q <= state["max_quarter"]:
        return "bulk", None
    if not no_refresh:
        print(f"[13f] {q} beyond bulk max {state['max_quarter']} — trying SEC bulk append")
        subprocess.run([PY, str(REPO / "refresh/refresh_13f.py")], check=False)
        state = json.loads((REPO / "data/13f/13f_holdings_slim.state.json").read_text())
        if q <= state["max_quarter"]:
            return "bulk", None
        print(f"[13f] SEC bulk not yet published — fetching individual 13F-HR filings")
        subprocess.run([PY, str(REPO / "refresh/fetch_13f_filings.py"), "--quarter", q],
                       check=False)
    manifest = REPO / f"data/13f/provisional/13f_provisional_{q}.manifest.json"
    if not manifest.exists():
        sys.exit(f"[13f] no bulk or provisional data for {q} — wait for filings")
    m = json.loads(manifest.read_text())
    n_filed = m.get("n_filed", 0)
    n_expected = m.get("n_expected") or m.get("n_requested") or len(managers.load_tier_map())
    coverage = n_filed / n_expected if n_expected else 0.0
    min_cov = config.load()["provisional"]["min_coverage"]
    if coverage < min_cov:
        sys.exit(f"[13f] provisional coverage {coverage:.0%} < {min_cov:.0%} — wait for more filings")
    print(f"[13f] PROVISIONAL mode, coverage {coverage:.0%}")
    return "provisional", coverage


# ---------- pipeline stages ----------

def build_hc(q: str, mode: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (major_purchases all quarters, HC rows for q)."""
    tm = managers.load_tier_map()
    provisional = [q] if mode == "provisional" else None
    hd = h_mod.load_holdings(ciks=sorted(tm.keys()), provisional=provisional)
    actions = signals.build_actions(hd, start_quarter="2014Q1")
    cutoff = ranks.formation_date(q).strftime("%Y-%m-%d")
    comp = da.load_compstat_for_actions(cutoff=cutoff)
    cw = da.load_cusip_ticker_pit()
    actions = signals.resolve_tickers(actions, cw, comp)
    actions["manager_name"] = actions["cik"].map(h_mod.latest_manager_names(sorted(tm.keys())))
    mp = actions.rename(columns={"shares": "shares_t", "value_thousands": "value_thousands_t"})
    mp = bands.add_hc_alt(mp, mp)
    hc_min = config.load()["bands"]["hc_min_weight"]
    hc_rows = mp[(mp["quarter"] == q) & (mp["hc_alt_weight"].fillna(0) >= hc_min)].copy()
    return mp, hc_rows


def run_quant(hc_rows: pd.DataFrame, cutoff: str, outdir: Path) -> pd.DataFrame:
    n_unresolved = hc_rows["ticker"].isna().sum()
    if n_unresolved:
        lost = hc_rows[hc_rows["ticker"].isna()]["cusip"].unique()
        print(f"[quant] {n_unresolved} HC rows with unresolved ticker dropped "
              f"(cusips: {', '.join(lost[:5])}{'...' if len(lost) > 5 else ''})")
    hc_rows = hc_rows.dropna(subset=["ticker"])
    scr = s_mod.run_screen(hc_rows, cutoff=cutoff, live_pe=False)
    if "passes_quant" not in scr.columns:
        flags = scr.apply(derive_flags, axis=1, result_type="expand")
        scr = pd.concat([scr, flags.loc[:, ~flags.columns.isin(scr.columns)]], axis=1)
        scr["passes_quant"] = scr[[c for c in scr.columns
                                   if c.startswith("pass_")]].all(axis=1)
    scr = scr.merge(hc_rows[["cik", "quarter", "cusip", "hc_alt_weight"]],
                    on=["cik", "quarter", "cusip"], how="left", suffixes=("", "_hc"))
    if "hc_alt_weight" not in scr.columns and "hc_alt_weight_hc" in scr.columns:
        scr["hc_alt_weight"] = scr["hc_alt_weight_hc"]
    scr.to_csv(outdir / "01_screen.csv", index=False)
    return scr


def patch_stale(cand: pd.DataFrame, ranked: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    """EDGAR companyfacts patch for names whose Compustat datadate is stale.
    Returns {ticker: {mf_pct, ey, roc, end_date}} overrides."""
    from refresh.refresh_fundamentals import fetch_fresh_metrics
    stale_days = config.load()["fundamentals"]["stale_days"]
    g2d = ranked.set_index("gvkey")["datadate"].to_dict()
    stale = []
    for r in cand.itertuples():
        dd = g2d.get(r.gvkey)
        if dd is not None and (cutoff - pd.Timestamp(dd)).days > stale_days:
            stale.append(r.ticker)
    if not stale:
        return {}
    print(f"[edgar] patching stale fundamentals: {', '.join(stale)}")
    caps = da.fetch_mkt_caps(stale, cutoff, cache_dir=REPO / "data/cache")
    out = {}
    t2g = cand.set_index("ticker")["gvkey"].to_dict()
    for t in stale:
        res = fetch_fresh_metrics(t, caps.get(t))
        comp_dd = g2d.get(t2g.get(t))
        if res["ok"] and comp_dd is not None and \
                pd.Timestamp(res["end_date"]) <= pd.Timestamp(comp_dd):
            print(f"  {t}: EDGAR ({res['end_date']}) not newer than Compustat "
                  f"({pd.Timestamp(comp_dd).date()}) — keep Compustat")
            continue
        if res["ok"]:
            pct = ranks.locate_pct(ranked, res["ey"], res["roc"])
            out[t] = {"mf_pct": pct, "ey": res["ey"], "roc": res["roc"],
                      "end_date": res["end_date"]}
            print(f"  {t}: EDGAR {res['end_date']} -> ey {res['ey']:.3f} roc {res['roc']:.2f} pct {pct:.3f}")
        else:
            print(f"  {t}: fallback to Compustat ({res['reason']})")
    return out


# ---------- funnel ----------

def build_funnel(q, scr, ranked, overrides, macro_res, mode, coverage, outdir):
    cfg = config.load()["mf"]
    pct_map = ranked.set_index("gvkey")["mf_pct"].to_dict()
    dd_map = ranked.set_index("gvkey")["datadate"].to_dict()

    per = []
    for tkr, grp in scr.groupby("ticker"):
        best = grp.loc[grp["hc_alt_weight"].idxmax()]
        gvkey = best.get("gvkey")
        failed = sorted(c for c in grp.columns if c.startswith("pass_")
                        and not bool(grp[c].fillna(True).all()))
        quant = bool(grp["passes_quant"].any())
        ov = overrides.get(tkr)
        pct = ov["mf_pct"] if ov else pct_map.get(gvkey)
        mgrs = "; ".join(f"{r.manager_name} ({r.hc_alt_weight:.1%})"
                         for r in grp.sort_values("hc_alt_weight", ascending=False)
                         .itertuples() if pd.notna(r.manager_name))
        per.append({"ticker": tkr, "gvkey": gvkey, "conviction": best["hc_alt_weight"],
                    "managers": mgrs, "quant": quant, "failed_flags": ",".join(failed),
                    "mf_pct": pct, "edgar_patched": bool(ov),
                    "datadate": str(ov["end_date"] if ov else dd_map.get(gvkey, ""))[:10]})
    df = pd.DataFrame(per).sort_values("mf_pct", na_position="last").reset_index(drop=True)

    # outcomes
    eligible = df[(df["quant"]) & df["mf_pct"].notna() & (df["mf_pct"] <= cfg["pctile_cutoff"])]
    top = eligible.head(cfg["top_n"])["ticker"].tolist()
    blocked = {t for t in top if macro_res["_by_ticker"].get(t, {}).get("macro_blocked")}
    selected = [t for t in top if t not in blocked]

    def outcome(r):
        if pd.isna(r["mf_pct"]) and not r["gvkey"]:
            return "NO DATA: no_gvkey"
        if not r["quant"]:
            return f"CUT: quant ({r['failed_flags']})"
        if pd.isna(r["mf_pct"]):
            return "NO DATA: not in MF universe"
        if r["mf_pct"] > cfg["pctile_cutoff"]:
            return f"CUT: pctile {r['mf_pct']:.2f} > {cfg['pctile_cutoff']:.2f}"
        if r["ticker"] in blocked:
            return f"BLOCKED: macro ({macro_res['_by_ticker'][r['ticker']]['macro_reason']})"
        if r["ticker"] in selected:
            return "SELECTED"
        return f"CUT: rank > top {cfg['top_n']}"

    df["outcome"] = df.apply(outcome, axis=1)

    st = macro_res["_state"]
    lines = [f"# {q} — HC ∩ Magic Formula funnel", "",
             f"- Data mode: **{mode.upper()}**" + (f" (coverage {coverage:.0%})" if coverage else ""),
             f"- Cutoff: {ranks.formation_date(q).date()}",
             f"- MF universe ranked: {len(ranked):,} names",
             f"- Macro: S&P PE {st['sp_pe_ttm']:.1f}, gate "
             f"{'ACTIVE (block > $' + format(st['threshold_bn'], ',.0f') + 'bn cap)' if st['gate_active'] else 'dormant'}",
             "", f"## Portfolio ({len(selected)} names)", "",
             ", ".join(f"**{t}**" for t in selected), "",
             "## Funnel — every HC name", "",
             "| Ticker | Conviction | Quant | MF pctile | EDGAR | Outcome |",
             "|---|---|---|---|---|---|"]
    for r in df.itertuples():
        pct = f"{r.mf_pct:.3f}" if pd.notna(r.mf_pct) else "—"
        lines.append(f"| {r.ticker} | {r.conviction:.1%} | {'PASS' if r.quant else 'FAIL'} "
                     f"| {pct} | {'Y' if r.edgar_patched else ''} | {r.outcome} |")
    lines += ["", "## Detail", ""]
    for r in df.itertuples():
        lines += [f"### {r.ticker}",
                  f"- Managers: {r.managers}",
                  f"- Fundamentals as of: {r.datadate}"
                  + (" (EDGAR companyfacts)" if r.edgar_patched else " (Compustat)"),
                  f"- Failed quant flags: {r.failed_flags or 'none'}", ""]
    (outdir / "04_funnel.md").write_text("\n".join(lines), encoding="utf-8")
    # Position sizing: equal weight, capped at sizing.max_weight per ticker;
    # any remainder stays in cash (deployed in later, fuller quarters).
    max_w = config.load()["sizing"]["max_weight"]
    w = min(1.0 / len(selected), max_w) if selected else 0.0
    cash = 1.0 - w * len(selected)
    lines = [f"# {q} {mode.upper()}"]
    lines += [f"{t}\t{w:.1%}" for t in selected]
    if cash > 1e-9:
        lines.append(f"CASH\t{cash:.1%}")
    (outdir / "03_portfolio.txt").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")
    return selected, df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("quarter")
    ap.add_argument("--no-refresh", action="store_true",
                    help="skip 13F/macro network refresh (use local data as-is)")
    args = ap.parse_args()
    q = args.quarter
    outdir = REPO / "quarters" / q
    outdir.mkdir(parents=True, exist_ok=True)
    cutoff = ranks.formation_date(q)

    mode, coverage = ensure_13f(q, args.no_refresh)

    print("[hc] building conviction set...")
    mp, hc_rows = build_hc(q, mode)
    print(f"[hc] {hc_rows['ticker'].nunique()} HC names")

    print("[quant] screening...")
    scr = run_quant(hc_rows, cutoff.strftime("%Y-%m-%d"), outdir)

    print("[mf] ranking universe...")
    fund = ranks.load_universe()
    ranked = ranks.rank_quarter(fund, q)
    ranked.to_parquet(outdir / "02_ranks.parquet", index=False)

    cand = scr.drop_duplicates("ticker")[["ticker", "gvkey"]]
    overrides = patch_stale(cand, ranked, cutoff)

    print("[macro] evaluating gate...")
    if not args.no_refresh:
        subprocess.run([PY, str(REPO / "refresh/refresh_macro.py")], check=False)
    hc_tickers = sorted(scr["ticker"].dropna().unique())
    macro_res = macro.evaluate(hc_tickers, cutoff)

    selected, funnel = build_funnel(q, scr, ranked, overrides, macro_res,
                                    mode, coverage, outdir)
    print(f"\n{q} portfolio ({mode}): {', '.join(selected)}")
    print(f"funnel: {outdir / '04_funnel.md'}")


if __name__ == "__main__":
    main()
