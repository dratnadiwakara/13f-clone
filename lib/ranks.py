"""Global magic-formula ranks, point-in-time per quarter.

Universe: all Compustat USD names with market cap >= mf.min_cap_musd,
excluding gsector values in mf.exclude_gsector (utilities) and US federally
regulated depositories only (fic == 'USA' with a depository SIC, or ticker on
the hard_excludes.depositories list). Foreign financials (e.g. KSPI) stay in.

Earnings yield = EBIT / EV, EV = mkt cap + dltt + dlc + mib - che.
Return on capital = EBIT / (max(NWC, 0) + net PP&E), NWC = act - lct
(fallback wcap). mf_pct = combined-rank percentile, 0 = best.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config, data_access as da

COLS = ["gvkey", "tic", "cusip", "datadate", "fyear", "fic", "curcd", "indfmt",
        "gsector", "sic", "ebit", "oiadp", "act", "lct", "wcap", "ppent", "che",
        "dltt", "dlc", "mib", "mkvalt", "prcc_f", "csho"]


def quarter_end(q: str) -> pd.Timestamp:
    y, qn = int(q[:4]), int(q[-1])
    m, d = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[qn]
    return pd.Timestamp(y, m, d)


def formation_date(q: str) -> pd.Timestamp:
    return quarter_end(q) + pd.Timedelta(days=50)


def load_universe() -> pd.DataFrame:
    """One-time load of the full USD panel; pass to rank_quarter for reuse."""
    fund = da.load_fund(columns=COLS)
    fund = fund[fund["curcd"] == "USD"].copy()
    fund["_fmt"] = (fund["indfmt"] != "INDL").astype(int)  # prefer INDL on dedupe
    return fund


def _is_us_depository(f: pd.DataFrame) -> pd.Series:
    cfg = config.load()
    sics = set(cfg["mf"]["depository_sic"])
    hard = set(cfg["hard_excludes"]["depositories"])
    sic = pd.to_numeric(f["sic"], errors="coerce")
    return ((f["fic"] == "USA") & sic.isin(sics)) | f["tic"].isin(hard)


def rank_quarter(fund: pd.DataFrame, q: str) -> pd.DataFrame:
    cfg = config.load()["mf"]
    cut = formation_date(q)
    lag = pd.Timedelta(days=cfg["filing_lag_days"])
    max_age = pd.Timedelta(days=cfg["max_age_days"])

    f = fund[(fund["datadate"] + lag <= cut) & (fund["datadate"] >= cut - max_age)]
    f = f.sort_values(["gvkey", "datadate", "_fmt"]).drop_duplicates("gvkey", keep="last").copy()

    gs = pd.to_numeric(f["gsector"], errors="coerce")
    f = f[~gs.isin(cfg["exclude_gsector"])]
    f = f[~_is_us_depository(f)]

    f["mkt_cap"] = f["mkvalt"].fillna(f["prcc_f"] * f["csho"])
    f = f[f["mkt_cap"] >= cfg["min_cap_musd"]]

    f["ebit_use"] = f["ebit"].fillna(f["oiadp"])
    f["ev"] = (f["mkt_cap"] + f[["dltt", "dlc", "mib"]].fillna(0).sum(axis=1)
               - f["che"].fillna(0))
    # NWC = act - lct, fallback wcap; firms reporting no current-asset split
    # (banks/financial balance sheets, e.g. KSPI) get NWC = 0 so ROC stays
    # computable as EBIT / net PP&E rather than dropping out of the universe.
    nwc = (f["act"] - f["lct"]).where(f["act"].notna() & f["lct"].notna(), f["wcap"])
    f["cap_employed"] = nwc.fillna(0).clip(lower=0) + f["ppent"].fillna(0)

    f["ey"] = np.where((f["ev"] > 0) & f["ebit_use"].notna(), f["ebit_use"] / f["ev"], np.nan)
    f["roc"] = np.where(f["cap_employed"] > 0, f["ebit_use"] / f["cap_employed"], np.nan)
    f = f.dropna(subset=["ey", "roc"]).copy()

    f["ey_rank"] = f["ey"].rank(ascending=False)
    f["roc_rank"] = f["roc"].rank(ascending=False)
    f["combined_rank"] = (f["ey_rank"] + f["roc_rank"]).rank(method="first")
    f["mf_pct"] = f["combined_rank"] / len(f)
    f["quarter"] = q
    return f[["quarter", "gvkey", "tic", "datadate", "mkt_cap", "ebit_use", "ev",
              "cap_employed", "ey", "roc", "ey_rank", "roc_rank",
              "combined_rank", "mf_pct"]]


def locate_pct(ranked: pd.DataFrame, ey: float, roc: float) -> float:
    """Percentile a fresh (ey, roc) pair would take in an existing ranked
    quarter, without rebuilding ranks. Used by the EDGAR fundamentals patch."""
    n = len(ranked)
    ey_rank = (ranked["ey"] > ey).sum() + 1
    roc_rank = (ranked["roc"] > roc).sum() + 1
    combined = (ranked["ey_rank"] + ranked["roc_rank"] < ey_rank + roc_rank).sum() + 1
    return combined / n
