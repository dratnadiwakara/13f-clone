"""Compute hc_alt_weight (trailing-4Q cumulative dollar-weight of buying by
(cik, cusip)) and split screen rows into HC / MC bands.

hc_alt_weight sums incremental_value_thousands over trailing 4 quarters
per (cik, cusip), divided by current portfolio_value_thousands. Uses
dollar-cost basis of purchases — price appreciation alone never lifts it.

HC: hc_alt_weight >= hc_min_weight AND passes_quant
MC: mc_min_weight <= hc_alt_weight < hc_min_weight AND passes_quant
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from . import config


def _quarter_index(q: str) -> int:
    return int(q[:4]) * 4 + int(q[-1]) - 1


def add_hc_alt(major_purchases: pd.DataFrame, screen: pd.DataFrame) -> pd.DataFrame:
    mp = major_purchases.copy()
    mp["qidx"] = mp["quarter"].map(_quarter_index)
    mp["cik"] = mp["cik"].astype(str).str.zfill(10)
    mp = mp.sort_values(["cik", "cusip", "qidx"]).reset_index(drop=True)

    rows = []
    for (cik, cusip), grp in mp.groupby(["cik", "cusip"], sort=False):
        g = grp.sort_values("qidx")
        qidx_arr = g["qidx"].to_numpy()
        inc_arr = g["incremental_value_thousands"].fillna(0).to_numpy()
        cum = np.zeros(len(g))
        for i, qi in enumerate(qidx_arr):
            mask = (qidx_arr >= qi - 3) & (qidx_arr <= qi)
            cum[i] = inc_arr[mask].sum()
        g = g.copy()
        g["cum_inc_value_4q"] = cum
        rows.append(g)

    mp_aug = pd.concat(rows, ignore_index=True)
    mp_aug["hc_alt_weight"] = mp_aug["cum_inc_value_4q"] / mp_aug["portfolio_value_thousands"]

    screen = screen.copy()
    screen["cik"] = screen["cik"].astype(str).str.zfill(10)
    key = ["cik", "quarter", "cusip"]
    aug = mp_aug[key + ["cum_inc_value_4q", "hc_alt_weight"]].drop_duplicates(key)
    return screen.merge(aug, on=key, how="left")


def score_buys(screen: pd.DataFrame, tier_map: dict[str, str]) -> pd.DataFrame:
    df = screen.copy()
    df["manager_tier"] = df["cik"].astype(str).str.zfill(10).map(tier_map).fillna("Other")
    keep = [
        "cik", "manager_name", "manager_tier",
        "quarter", "ticker", "cusip", "issuer_name",
        "archetype", "quality_tier",
        "position_weight", "incremental_weight", "hc_alt_weight",
        "pass_leverage", "pass_intcov", "pass_maturity_cliff",
        "pass_clean_earnings", "pass_loss_year", "pass_revenue",
        "pass_cash_conversion", "pass_franchise", "pass_quality_gate",
        "pass_depository_exclude", "pass_etf_exclude",
        "passes_quant",
    ]
    out = df[[c for c in keep if c in df.columns]].copy()
    return out.sort_values(["cik", "position_weight"], ascending=[True, False])


def _dedup_band(band_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "ticker", "n_managers", "n_elite_managers",
        "max_hc_alt_weight", "max_position_weight",
        "manager_list", "archetype", "quality_tier",
    ]
    if band_df.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for ticker, g in band_df.groupby("ticker"):
        managers = g.sort_values("position_weight", ascending=False)
        mlist = ", ".join(
            f"{r.manager_name} ({r.position_weight*100:.1f}%)"
            for r in managers.itertuples()
        )
        rows.append({
            "ticker": ticker,
            "n_managers": g["cik"].nunique(),
            "n_elite_managers": (g["manager_tier"] == "Elite").sum(),
            "max_hc_alt_weight": g["hc_alt_weight"].max(),
            "max_position_weight": g["position_weight"].max(),
            "manager_list": mlist,
            "archetype": g["archetype"].iloc[0],
            "quality_tier": g["quality_tier"].iloc[0] if "quality_tier" in g else None,
        })
    return pd.DataFrame(rows).sort_values("max_hc_alt_weight", ascending=False)


def split_bands(scored: pd.DataFrame,
                hc_min: float | None = None,
                mc_min: float | None = None):
    cfg = config.load()["bands"]
    hc_min = hc_min if hc_min is not None else cfg["hc_min_weight"]
    mc_min = mc_min if mc_min is not None else cfg["mc_min_weight"]
    base = scored[scored["passes_quant"]].copy()
    hc = base[base["hc_alt_weight"] >= hc_min]
    mc = base[(base["hc_alt_weight"] >= mc_min) & (base["hc_alt_weight"] < hc_min)]
    return _dedup_band(hc), _dedup_band(mc)
