"""Full-universe efficacy test of the 11 quant screen filters.

Question asked here is NOT "do these filters pick winners" but "do they avoid
bad companies". `backtest/VARIANTS.md` §7 only ever measured the flags inside
the strategy, on the HC candidate pool (~132 names, 288 of 325 name-quarters
from one manager), by FULL XIRR — a metric §8 then showed carries a ~2.6 pt
noise floor. Avoiding disasters is a left-tail claim about a large
cross-section, so test it on the whole Compustat panel instead.

Design notes that matter:

  * Grain is firm-YEAR, not firm-quarter. gvkey+fyear is effectively unique
    and per_gvkey_metrics is the expensive step, so this is ~25x cheaper than
    replaying 44 formation quarters.
  * Returns come from Compustat in-panel: adj_px = prcc_f / ajex (ajex is a
    cumulative divisor). Fiscal-year to fiscal-year, dividend-blind. Dividend
    blindness penalises mature payers, who cluster in the PASS arm, so it
    biases against the filters — a positive result here is conservative.
  * Delisted firms are classified via dlrsn and CONTRIBUTE a return. They are
    never dropped: silently dropping unpriced names is exactly the mechanism
    VARIANTS.md §8 found was inflating FULL XIRR by ~1.6 pt.
  * Unlike lib/ranks.load_universe, utilities and US depositories are NOT
    pre-excluded — pass_depository_exclude is one of the filters under test.
  * costat is a static as-of-today flag, so it is never used to filter the
    historical universe. Doing so would delete 37.6% of the 2015 opportunity
    set and reintroduce survivorship bias.
  * CIs come from a cluster bootstrap over gvkey. The same firm contributes up
    to 16 firm-years and at a 10y horizon consecutive observations share 9 of
    10 years, so naive binomial intervals are far too narrow.

    python backtest/filter_efficacy.py --rebuild
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import data_access as da  # noqa: E402
from lib import screen as S  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
OUT = Path(__file__).resolve().parent / "outputs"

FLAGS = [
    "pass_leverage", "pass_intcov", "pass_maturity_cliff", "pass_clean_earnings",
    "pass_loss_year", "pass_revenue", "pass_cash_conversion", "pass_franchise",
    "pass_quality_gate", "pass_depository_exclude", "pass_etf_exclude",
]

HORIZONS = [1, 3, 5, 10]
MIN_CAP_MUSD = 50.0          # mirrors config mf.min_cap_musd
SEVERE_DD = -0.50
CATASTROPHIC_DD = -0.80
N_BOOT = 1000
BOOT_SEED = 20260823

# Bankruptcy (dlrsn 02) wipes common equity in the overwhelming majority of
# cases, but the last reported fiscal price only shows a -64% median: Compustat
# stops updating well before the equity actually goes to zero. Forcing -100%
# is the single most consequential judgement call in this file, hence the
# toggle — `--no-bankrupt-zero` re-runs the whole study with last-price
# instead, as a robustness check.
BANKRUPT_ZERO = True

# dlrsn buckets. 01/03 are deal outcomes (median last-year return ~0), the
# 02/04/07/09/05/20 group is genuine failure, and 10 ("no longer files, reason
# unavailable", 2,585 gvkeys) is ambiguous enough that folding it into either
# arm would be a choice rather than a measurement — it gets its own column.
DLRSN_ACQUIRED = {"01", "03"}
DLRSN_FAILED = {"02", "04", "05", "07", "09", "20"}
DLRSN_UNKNOWN = {"10"}

# Columns per_gvkey_metrics reads, plus identity/return/delisting fields.
COLS = sorted(set([
    "gsector", "gind", "sic", "indfmt", "at", "dptc", "dptb",
    "ivaeq", "intan", "gdwl", "ppent", "invt", "rect", "che",
    "act", "lct", "wcap",
    "seq", "ceq", "ceqt", "mib", "dltt", "dlc", "dt",
    "dd1", "dd2", "ni", "ib", "revt", "sale", "cogs", "xsga",
    "oibdp", "oiadp", "ebit", "ebitda", "dp", "xint", "pi", "txt",
    "xido", "spi", "nopi", "xrd", "epsfx", "csho", "mkvalt",
    "oancf", "capx", "prstkc", "sstk", "dvc", "dvt",
    "dltis", "dltr", "prcc_f",
    "gvkey", "tic", "conm", "datadate", "fyear", "curcd", "fic",
    "ajex", "costat", "dlrsn", "dldte",
]))


# --------------------------------------------------------------------------
# Stage 1: flags
# --------------------------------------------------------------------------

def build_flag_panel() -> pd.DataFrame:
    """Run the production screen chain over every cap-qualifying firm-year."""
    fund = da.load_fund(columns=COLS)
    fund = fund[fund["curcd"] == "USD"].copy()
    fund = fund.sort_values(["gvkey", "datadate"])
    fund = fund.drop_duplicates(["gvkey", "fyear"], keep="last")

    cap = fund["mkvalt"].fillna(fund["prcc_f"] * fund["csho"])
    fund["cap"] = cap
    eligible = fund[fund["cap"] >= MIN_CAP_MUSD].copy()
    print(f"[flags] {len(fund):,} USD firm-years, "
          f"{len(eligible):,} with cap >= ${MIN_CAP_MUSD:.0f}M "
          f"({eligible['gvkey'].nunique():,} gvkeys)")

    keep_ids = set(zip(eligible["gvkey"], eligible["datadate"]))
    rows = []
    n_gv = fund["gvkey"].nunique()
    # safe_div / cagr divide by zero constantly by design; the warnings are
    # benign and would otherwise bury real output.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        old = np.seterr(all="ignore")
        try:
            for i, (gv, g) in enumerate(fund.groupby("gvkey", sort=False)):
                if i % 2000 == 0:
                    print(f"[flags] {i:,}/{n_gv:,} gvkeys", flush=True)
                tic_raw = g["tic"].iloc[-1]
                # derive_flags does `(row.get("ticker") or "").upper()`, which
                # blows up on a float NaN (NaN is truthy, so `or` never fires).
                # Guard on isinstance, not pd.notna — a non-string scalar would
                # still crash. Fixed caller-side; lib/screen.py is untouched.
                tkr = tic_raw.upper().strip() if isinstance(tic_raw, str) else ""
                # WRDS recycles tickers and marks the duplicates "FST.1",
                # "BEAM.2". Strip the marker so hard_excludes membership works.
                tkr = tkr.split(".")[0]
                for _, r in g.iterrows():
                    if (gv, r["datadate"]) not in keep_ids:
                        continue
                    m = S.per_gvkey_metrics(g, r["datadate"])
                    if m.get("_missing"):
                        continue
                    arche, arche_reason = S.tag_archetype({**m, "ticker": tkr})
                    if arche in S.GATED_ARCHETYPES:
                        qgp, qreason = S.quality_gate(arche, m)
                    else:
                        qgp, qreason = None, f"archetype_{arche}_no_gate"
                    row = {k: v for k, v in m.items() if not k.startswith("_")}
                    row.update({
                        "gvkey": gv,
                        "fyear": r["fyear"],
                        "datadate": r["datadate"],
                        "ticker": tkr,
                        "conm": r.get("conm"),
                        "gsector": r.get("gsector"),
                        "sic_raw": r.get("sic"),
                        "fic": r.get("fic"),
                        "cap": r["cap"],
                        "archetype": arche,
                        "archetype_reason": arche_reason,
                        "quality_gate_passed": qgp,
                        "quality_gate_reason": qreason,
                    })
                    row.update(S.derive_flags(pd.Series(row)))
                    rows.append(row)
        finally:
            np.seterr(**old)

    out = pd.DataFrame(rows)
    out = out.drop_duplicates(["gvkey", "fyear"], keep="last")
    # safe_div returns 0-d numpy arrays via np.where, so those columns land as
    # object dtype and parquet refuses them. Coerce anything numeric-ish.
    keep_obj = {"gvkey", "ticker", "conm", "archetype", "archetype_reason",
                "quality_gate_reason", "datadate", "datadate_used",
                "quality_gate_passed"} | set(FLAGS) | {"passes_quant"}
    for c in out.columns:
        if c in keep_obj or out[c].dtype != object:
            continue
        out[c] = pd.to_numeric(
            out[c].map(lambda v: v.item() if hasattr(v, "item") else v),
            errors="coerce")
    print(f"[flags] {len(out):,} firm-years scored, "
          f"passes_quant rate {out['passes_quant'].mean():.1%}")
    return out


# --------------------------------------------------------------------------
# Stage 2: returns
# --------------------------------------------------------------------------

def build_return_panel(horizons: list[int], bankrupt_zero: bool) -> pd.DataFrame:
    """Forward returns per (gvkey, fyear, horizon), delistings classified."""
    fund = da.load_fund(columns=["gvkey", "fyear", "datadate", "prcc_f", "ajex",
                                 "costat", "dlrsn", "dldte", "curcd"])
    fund = fund[fund["curcd"] == "USD"].copy()
    fund = fund.sort_values(["gvkey", "datadate"]).drop_duplicates(
        ["gvkey", "fyear"], keep="last")
    fund["adj_px"] = fund["prcc_f"] / fund["ajex"]
    fund = fund[fund["adj_px"] > 0]

    max_fyear = int(fund["fyear"].max())

    px = fund.pivot_table(index="gvkey", columns="fyear", values="adj_px")
    dd = fund.pivot_table(index="gvkey", columns="fyear", values="datadate",
                          aggfunc="last")

    # Terminal state per gvkey: last observed adjusted price + why it stopped.
    last = fund.sort_values("datadate").groupby("gvkey").last()
    meta = fund.sort_values("datadate").groupby("gvkey").agg(
        costat=("costat", "last"), dlrsn=("dlrsn", "last"),
        last_fyear=("fyear", "last"), last_px=("adj_px", "last"),
        last_dd=("datadate", "last"))

    def kind_of(costat, dlrsn):
        if costat == "I":
            d = str(dlrsn).strip() if pd.notna(dlrsn) else ""
            if d in DLRSN_ACQUIRED:
                return "acquired"
            if d in DLRSN_FAILED:
                return "failed"
            if d in DLRSN_UNKNOWN:
                return "dropped_unknown"
            return "dropped_unknown"
        return "stale_active"

    meta["terminal_kind"] = [kind_of(c, d) for c, d in
                             zip(meta["costat"], meta["dlrsn"])]

    recs = []
    fyears = sorted(c for c in px.columns if pd.notna(c))
    for H in horizons:
        for f0 in fyears:
            fH = f0 + H
            if fH > max_fyear:
                continue          # true right-censoring, not an outcome
            if f0 not in px.columns:
                continue
            p0 = px[f0].dropna()
            if p0.empty:
                continue
            d0 = dd[f0].reindex(p0.index)
            pH = px[fH].reindex(p0.index) if fH in px.columns else pd.Series(
                np.nan, index=p0.index)
            dH = dd[fH].reindex(p0.index) if fH in dd.columns else pd.Series(
                pd.NaT, index=p0.index)

            frame = pd.DataFrame({
                "gvkey": p0.index, "fyear": f0, "horizon": H,
                "adj_px_0": p0.values, "adj_px_H": pH.values,
                "dd_0": d0.values, "dd_H": dH.values,
            })
            frame = frame.join(meta, on="gvkey")

            alive = frame["adj_px_H"].notna()
            elapsed = (pd.to_datetime(frame["dd_H"]) -
                       pd.to_datetime(frame["dd_0"])).dt.days
            frame["elapsed_days"] = elapsed
            # A fiscal-year-end change makes "H fiscal years" stop meaning
            # "H calendar years". Those observations are dropped, not salvaged.
            bad_span = alive & (elapsed.sub(H * 365).abs() > 120)

            frame["ret"] = np.where(alive, frame["adj_px_H"] / frame["adj_px_0"] - 1,
                                    np.nan)
            frame["terminal_kind"] = np.where(alive, "alive", frame["terminal_kind"])

            # Terminal cases: the firm stopped reporting inside the horizon.
            # Return is measured to the last price it ever showed, so the
            # observation still counts rather than vanishing from the cohort.
            dead = ~alive
            term_ret = frame["last_px"] / frame["adj_px_0"] - 1
            frame.loc[dead, "ret"] = term_ret[dead]
            failed = dead & frame["terminal_kind"].eq("failed")
            frame.loc[failed, "ret"] = frame.loc[failed, "ret"].clip(lower=-1.0)
            if bankrupt_zero:
                bk = dead & frame["dlrsn"].astype(str).str.strip().eq("02")
                frame.loc[bk, "ret"] = -1.0

            # A firm that stopped reporting AFTER the horizon closed is not a
            # delisting for this horizon — we just lack a price at fH.
            late = dead & (frame["last_fyear"] > fH)
            frame.loc[late, "terminal_kind"] = "gap"

            frame = frame[~bad_span]
            frame = frame[frame["ret"].notna()]
            recs.append(frame[["gvkey", "fyear", "horizon", "ret",
                               "terminal_kind", "dlrsn", "elapsed_days",
                               "adj_px_0", "adj_px_H"]])

    out = pd.concat(recs, ignore_index=True)
    out["is_severe_dd"] = out["ret"] < SEVERE_DD
    out["is_catastrophic"] = out["ret"] < CATASTROPHIC_DD
    out["is_failed"] = out["terminal_kind"] == "failed"
    out["is_acquired"] = out["terminal_kind"] == "acquired"
    out["is_unknown_delist"] = out["terminal_kind"] == "dropped_unknown"
    for H in horizons:
        sub = out[out["horizon"] == H]
        print(f"[returns] H={H:2d}y  n={len(sub):,}  "
              f"gvkeys={sub['gvkey'].nunique():,}  "
              f"severe={sub['is_severe_dd'].mean():.1%}  "
              f"failed={sub['is_failed'].mean():.1%}")
    return out


# --------------------------------------------------------------------------
# Stage 3: cohort metrics
# --------------------------------------------------------------------------

def cohort_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "n_clusters": 0}
    r = df["ret"].values
    q10 = np.nanpercentile(r, 10)
    return {
        "n": len(df),
        "n_clusters": df["gvkey"].nunique(),
        "rate_severe_dd": float(df["is_severe_dd"].mean()),
        "rate_catastrophic": float(df["is_catastrophic"].mean()),
        "rate_failed": float(df["is_failed"].mean()),
        "rate_acquired": float(df["is_acquired"].mean()),
        "rate_unknown_delist": float(df["is_unknown_delist"].mean()),
        "p10": float(q10),
        "p25": float(np.nanpercentile(r, 25)),
        "median": float(np.nanmedian(r)),
        "mean_ret": float(np.nanmean(r)),   # reported, NOT the objective
        "skew": float(stats.skew(r, nan_policy="omit")),
        "cvar10": float(np.nanmean(r[r <= q10])) if (r <= q10).any() else np.nan,
    }


def cluster_bootstrap_delta(pass_df, fail_df, col, n_boot=N_BOOT, seed=BOOT_SEED):
    """CI on fail-rate minus pass-rate, resampling whole gvkeys.

    Observations overlap heavily (one firm supplies up to 16 firm-years; at
    H=10 neighbouring rows share 9 of 10 years), so the independent-sample CI
    is roughly 4x too narrow and would make every filter look significant.

    Implemented as per-gvkey sufficient statistics — (hits, count) in each arm —
    so a draw is four vector gathers instead of concatenating thousands of
    frames. Same estimator, ~1000x faster.
    """
    rng = np.random.default_rng(seed)
    if pass_df.empty or fail_df.empty:
        return np.nan, np.nan

    def agg(df):
        g = df.groupby("gvkey")[col].agg(["sum", "count"])
        return g["sum"].astype(float), g["count"].astype(float)

    ps, pc = agg(pass_df)
    fs, fc = agg(fail_df)
    gvs = ps.index.union(fs.index)
    ps = ps.reindex(gvs, fill_value=0.0).values
    pc = pc.reindex(gvs, fill_value=0.0).values
    fs = fs.reindex(gvs, fill_value=0.0).values
    fc = fc.reindex(gvs, fill_value=0.0).values

    n = len(gvs)
    idx = rng.integers(0, n, size=(n_boot, n))
    PS, PC = ps[idx].sum(1), pc[idx].sum(1)
    FS, FC = fs[idx].sum(1), fc[idx].sum(1)
    ok = (PC > 0) & (FC > 0)
    if not ok.any():
        return np.nan, np.nan
    deltas = FS[ok] / FC[ok] - PS[ok] / PC[ok]
    return float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))


def _delta_row(flag, horizon, pass_df, fail_df, min_clusters, min_n, boot=True):
    mp, mf = cohort_metrics(pass_df), cohort_metrics(fail_df)
    thin = (min(mp.get("n_clusters", 0), mf.get("n_clusters", 0)) < min_clusters
            or min(mp.get("n", 0), mf.get("n", 0)) < min_n)
    row = {
        "flag": flag, "horizon": horizon,
        "n_pass": mp.get("n", 0), "n_fail": mf.get("n", 0),
        "clusters_pass": mp.get("n_clusters", 0),
        "clusters_fail": mf.get("n_clusters", 0),
        "flag_thin": thin,
    }
    if thin:
        return row
    for k in ["rate_severe_dd", "rate_catastrophic", "rate_failed", "p10",
              "p25", "median", "mean_ret"]:
        row[f"{k}_pass"] = mp[k]
        row[f"{k}_fail"] = mf[k]
        row[f"{k}_delta"] = mf[k] - mp[k]
    row["lift_severe_dd"] = (mf["rate_severe_dd"] / mp["rate_severe_dd"]
                             if mp["rate_severe_dd"] > 0 else np.nan)
    row["lift_failed"] = (mf["rate_failed"] / mp["rate_failed"]
                          if mp["rate_failed"] > 0 else np.nan)
    if boot:
        lo, hi = cluster_bootstrap_delta(pass_df, fail_df, "is_severe_dd")
        row["severe_dd_ci_low"], row["severe_dd_ci_high"] = lo, hi
        row["severe_dd_signif"] = bool(pd.notna(lo) and lo > 0)
    return row


def build_tables(obs, horizons, min_clusters, min_n):
    standalone, marginal, cohorts = [], [], []
    for H in horizons:
        oh = obs[obs["horizon"] == H]
        if oh.empty:
            continue
        for flag in FLAGS:
            p, f = oh[oh[flag]], oh[~oh[flag]]
            for name, sub in (("pass", p), ("fail", f)):
                cohorts.append({"flag": flag, "horizon": H, "cohort": name,
                                **cohort_metrics(sub)})
            standalone.append(_delta_row(flag, H, p, f, min_clusters, min_n))

            others = [c for c in FLAGS if c != flag]
            op = oh[oh[others].all(axis=1)]
            marginal.append(_delta_row(flag, H, op[op[flag]], op[~op[flag]],
                                       min_clusters, min_n))
    return (pd.DataFrame(cohorts), pd.DataFrame(standalone),
            pd.DataFrame(marginal))


# --------------------------------------------------------------------------
# Stage 4: size / sector controls
# --------------------------------------------------------------------------

def stratified_tables(obs, horizons, min_clusters, min_n):
    """A filter can look good purely by dodging micro-caps or biotech."""
    by_cap, by_sector = [], []
    for H in horizons:
        oh = obs[obs["horizon"] == H]
        if oh.empty:
            continue
        for flag in FLAGS:
            for terc, sub in oh.groupby("cap_tercile"):
                r = _delta_row(flag, H, sub[sub[flag]], sub[~sub[flag]],
                               min_clusters, min_n, boot=False)
                by_cap.append({**r, "cap_tercile": terc})
            for gs, sub in oh.groupby("gsector_str"):
                r = _delta_row(flag, H, sub[sub[flag]], sub[~sub[flag]],
                               min_clusters, min_n, boot=False)
                by_sector.append({**r, "gsector": gs})
    return pd.DataFrame(by_cap), pd.DataFrame(by_sector)


def matched_table(obs, horizons, min_clusters, min_n, seed=BOOT_SEED):
    """Match each failing firm-year to <=3 passers: same fyear, same sector,
    nearest log(cap). Isolates the filter from the size/sector confound.

    A filter that only rejects micro-cap biotech would post a huge raw delta
    purely by dodging a risky corner of the market. Matching on (fyear,
    gsector, log-cap) asks the narrower question: among otherwise comparable
    firms, does the rejected one blow up more often?
    """
    rng = np.random.default_rng(seed)
    rows = []
    for H in horizons:
        oh = obs[obs["horizon"] == H]
        if oh.empty:
            continue
        for flag in FLAGS:
            pass_idx, fail_idx = [], []
            for _, sub in oh.groupby(["fyear", "gsector_str"], sort=False):
                p = sub[sub[flag]]
                f = sub[~sub[flag]]
                if p.empty or f.empty:
                    continue
                p = p.sort_values("log_cap")
                pv = p["log_cap"].values
                pidx = p.index.values
                used = np.zeros(len(p), dtype=bool)
                lo = np.searchsorted(pv, f["log_cap"].values - 0.5)
                hi = np.searchsorted(pv, f["log_cap"].values + 0.5)
                for k, fi in enumerate(f.index.values):
                    a, b = lo[k], hi[k]
                    if b <= a:
                        continue
                    cand = np.flatnonzero(~used[a:b]) + a
                    if cand.size == 0:
                        continue
                    take = cand if cand.size <= 3 else rng.choice(
                        cand, size=3, replace=False)
                    used[take] = True
                    pass_idx.append(pidx[take])
                    fail_idx.append(fi)
            if not fail_idx:
                rows.append({"flag": flag, "horizon": H, "n_pass": 0,
                             "n_fail": 0, "flag_thin": True})
                continue
            mp = oh.loc[np.concatenate(pass_idx)]
            mf = oh.loc[np.asarray(fail_idx)]
            rows.append(_delta_row(flag, H, mp, mf, min_clusters, min_n,
                                   boot=False))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Stage 5: summary
# --------------------------------------------------------------------------

def write_summary(standalone, marginal, by_cap, by_sector, matched,
                  obs, horizons, bankrupt_zero, path):
    L = []
    L.append("FILTER EFFICACY — full Compustat universe, disaster avoidance")
    L.append("=" * 70)
    L.append("")
    L.append("Question: does each quant filter avoid BAD companies? Not: does it")
    L.append("pick winners. Primary metric is the rate of severe drawdown")
    L.append(f"(return < {SEVERE_DD:.0%}) in the REJECTED cohort minus the ACCEPTED")
    L.append("cohort. Positive delta = the filter is rejecting worse companies.")
    L.append("")
    L.append("Returns: Compustat prcc_f/ajex, fiscal-year to fiscal-year,")
    L.append("dividend-blind (biases AGAINST the filters). Delisted firms are")
    L.append("classified by dlrsn and retained, never dropped.")
    L.append(f"Bankruptcy (dlrsn 02) forced to -100%: {bankrupt_zero}")
    L.append(f"CIs: cluster bootstrap over gvkey, {N_BOOT} draws.")
    L.append("")
    for H in horizons:
        sub = obs[obs["horizon"] == H]
        if sub.empty:
            continue
        L.append(f"  H={H:2d}y: {len(sub):,} firm-years, "
                 f"{sub['gvkey'].nunique():,} firms, "
                 f"severe-dd base rate {sub['is_severe_dd'].mean():.1%}, "
                 f"failure base rate {sub['is_failed'].mean():.1%}")
    L.append("")

    for H in horizons:
        for label, tab in (("STANDALONE", standalone), ("MARGINAL", marginal)):
            t = tab[(tab["horizon"] == H)].copy()
            if t.empty:
                continue
            L.append("")
            L.append(f"{label} — horizon {H}y "
                     + ("(pass vs fail, whole universe)" if label == "STANDALONE"
                        else "(within names passing the other 10)"))
            L.append("-" * 70)
            ok = t[~t["flag_thin"]].sort_values("rate_severe_dd_delta",
                                                ascending=False)
            hdr = (f"{'flag':<26}{'n_fail':>8}{'clus':>7}"
                   f"{'sev_pass':>10}{'sev_fail':>10}{'delta':>9}{'lift':>7}"
                   f"{'sig':>5}")
            L.append(hdr)
            for _, r in ok.iterrows():
                sig = ("yes" if r.get("severe_dd_signif") is True else "no")
                lift = r.get("lift_severe_dd")
                L.append(f"{r['flag']:<26}{int(r['n_fail']):>8,}"
                         f"{int(r['clusters_fail']):>7,}"
                         f"{r['rate_severe_dd_pass']:>10.1%}"
                         f"{r['rate_severe_dd_fail']:>10.1%}"
                         f"{r['rate_severe_dd_delta']:>+9.1%}"
                         f"{(lift if pd.notna(lift) else float('nan')):>7.2f}"
                         f"{sig:>5}")
            thin = t[t["flag_thin"]]
            if len(thin):
                L.append(f"  NOT MEASURABLE (n_clusters or n below floor): "
                         + ", ".join(thin["flag"].tolist()))

    L.append("")
    L.append("")
    L.append("VERDICTS — 5y and 10y, marginal effect after size/sector matching")
    L.append("=" * 70)
    L.append("A filter is credible when the marginal delta is positive, the")
    L.append("size/sector-matched delta keeps the same sign, and the sign holds")
    L.append("across all 3 cap terciles and >=7 of 11 sectors.")
    L.append("")
    for flag in FLAGS:
        L.append(f"{flag}")
        for H in [h for h in (5, 10) if h in horizons]:
            m = marginal[(marginal["flag"] == flag) & (marginal["horizon"] == H)]
            mt = matched[(matched["flag"] == flag) & (matched["horizon"] == H)]
            if m.empty or bool(m.iloc[0]["flag_thin"]):
                nf = int(m.iloc[0]["n_fail"]) if not m.empty else 0
                cf = int(m.iloc[0]["clusters_fail"]) if not m.empty else 0
                L.append(f"  {H:2d}y  NOT MEASURABLE — only {nf:,} rejected "
                         f"firm-years / {cf:,} firms pass the other 10 flags")
                continue
            r = m.iloc[0]
            cap = by_cap[(by_cap["flag"] == flag) & (by_cap["horizon"] == H)
                         & (~by_cap["flag_thin"])]
            sec = by_sector[(by_sector["flag"] == flag)
                            & (by_sector["horizon"] == H)
                            & (~by_sector["flag_thin"])]
            cap_ok = int((cap["rate_severe_dd_delta"] > 0).sum()) if len(cap) else 0
            sec_ok = int((sec["rate_severe_dd_delta"] > 0).sum()) if len(sec) else 0
            mstr = "n/a"
            if len(mt) and not bool(mt.iloc[0]["flag_thin"]):
                mstr = f"{mt.iloc[0]['rate_severe_dd_delta']:+.1%}"
            L.append(f"  {H:2d}y  marginal {r['rate_severe_dd_delta']:+.1%} "
                     f"(sev {r['rate_severe_dd_pass']:.1%} kept vs "
                     f"{r['rate_severe_dd_fail']:.1%} rejected, "
                     f"lift {r['lift_severe_dd']:.2f}x) | "
                     f"matched {mstr} | "
                     f"cap terciles {cap_ok}/{len(cap)} | "
                     f"sectors {sec_ok}/{len(sec)} | "
                     f"{'SIGNIFICANT' if r.get('severe_dd_signif') is True else 'not significant'}")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")
    print(f"[out] {path}")


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true",
                    help="recompute the flag/return caches (~6 min)")
    ap.add_argument("--horizons", default="1,3,5,10")
    ap.add_argument("--min-n", type=int, default=200)
    ap.add_argument("--min-clusters", type=int, default=100)
    ap.add_argument("--no-bankrupt-zero", action="store_true",
                    help="robustness: value bankruptcies at last reported "
                         "price instead of -100%%")
    ap.add_argument("--suffix", default="",
                    help="appended to output filenames")
    args = ap.parse_args()

    horizons = [int(h) for h in args.horizons.split(",")]
    bankrupt_zero = BANKRUPT_ZERO and not args.no_bankrupt_zero
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    fpath = CACHE / "firm_year_flags.parquet"
    rpath = CACHE / ("firm_year_returns.parquet" if bankrupt_zero
                     else "firm_year_returns_nobz.parquet")

    if args.rebuild or not fpath.exists():
        build_flag_panel().to_parquet(fpath, index=False)
    flags = pd.read_parquet(fpath)

    if args.rebuild or not rpath.exists():
        build_return_panel(horizons, bankrupt_zero).to_parquet(rpath, index=False)
    rets = pd.read_parquet(rpath)
    rets = rets[rets["horizon"].isin(horizons)]

    keep = ["gvkey", "fyear", "gsector", "cap", "archetype", "ticker", "conm"] + FLAGS + ["passes_quant"]
    obs = rets.merge(flags[keep], on=["gvkey", "fyear"], how="inner")
    obs["gsector_str"] = obs["gsector"].apply(
        lambda x: str(int(float(x))) if pd.notna(x) else "NA")
    obs["log_cap"] = np.log(obs["cap"].clip(lower=1.0))
    # Terciles are recomputed per formation year so they are point-in-time —
    # a full-sample cut would leak later market levels into early cohorts.
    obs["cap_tercile"] = obs.groupby(["horizon", "fyear"])["cap"].transform(
        lambda s: pd.qcut(s, 3, labels=["small", "mid", "large"],
                          duplicates="drop") if s.nunique() >= 3 else "NA")
    obs["cap_tercile"] = obs["cap_tercile"].astype(str)
    print(f"[obs] {len(obs):,} observations, {obs['gvkey'].nunique():,} firms")

    cohorts, standalone, marginal = build_tables(
        obs, horizons, args.min_clusters, args.min_n)
    by_cap, by_sector = stratified_tables(
        obs, horizons, args.min_clusters, args.min_n)
    matched = matched_table(obs, horizons, args.min_clusters, args.min_n)

    sfx = args.suffix or ("" if bankrupt_zero else "_nobz")
    for name, tab in [("standalone", standalone), ("marginal", marginal),
                      ("cohorts", cohorts), ("by_capterc", by_cap),
                      ("by_sector", by_sector), ("matched", matched)]:
        p = OUT / f"filter_efficacy_{name}{sfx}.csv"
        tab.to_csv(p, index=False)
        print(f"[out] {p}")

    write_summary(standalone, marginal, by_cap, by_sector, matched, obs,
                  horizons, bankrupt_zero,
                  OUT / f"filter_efficacy_summary{sfx}.txt")


if __name__ == "__main__":
    main()
