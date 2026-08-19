"""Macro overlay: block buys when S&P PE > threshold AND mkt cap > 5% of GDP.

Reads GDP + S&P PE snapshots from parquets in `validation/backtest/cache/`.
Populate them via `validation/backtest/fetch_macro_pit.py`.
"""
from __future__ import annotations
import pandas as pd

from . import config, data_access as da


def macro_at(d: pd.Timestamp) -> tuple[float, float]:
    gdp = pd.read_parquet(config.path("gdp_parquet"))
    pe = pd.read_parquet(config.path("sp_pe_parquet"))
    gdp["date"] = pd.to_datetime(gdp["date"])
    pe["date"] = pd.to_datetime(pe["date"])
    g = gdp[gdp["date"] <= d]
    p = pe[pe["date"] <= d]
    gdp_bn = float(g.iloc[-1]["gdp_bn"]) if not g.empty else float("nan")
    sp_pe = float(p.iloc[-1]["sp_pe_ttm"]) if not p.empty else float("nan")
    return gdp_bn, sp_pe


def evaluate(tickers: list[str], as_of: pd.Timestamp) -> dict[str, dict]:
    cfg = config.load()["macro"]
    pe_cutoff = cfg["sp500_pe_threshold"]
    mktcap_frac = cfg["mktcap_over_gdp_threshold"]
    gdp_bn, sp_pe = macro_at(as_of)
    state = {
        "gdp_bn": gdp_bn,
        "sp_pe_ttm": sp_pe,
        "gate_active": sp_pe > pe_cutoff,
        "threshold_bn": mktcap_frac * gdp_bn,
    }
    result = {"_state": state, "_by_ticker": {}}
    if not state["gate_active"]:
        for t in tickers:
            result["_by_ticker"][t] = {
                "macro_blocked": False,
                "macro_reason": f"sp_pe={sp_pe:.1f}<={pe_cutoff:.0f}_gate_dormant",
                "mkt_cap_bn": None,
            }
        return result

    caps = da.fetch_mkt_caps(tickers, as_of)
    for t in tickers:
        cap_m = caps.get(t)
        if cap_m is None or pd.isna(cap_m):
            result["_by_ticker"][t] = {
                "macro_blocked": False,
                "macro_reason": "no_mktcap_data",
                "mkt_cap_bn": None,
            }
            continue
        cap_bn = float(cap_m) / 1000.0
        blocked = cap_bn > state["threshold_bn"]
        result["_by_ticker"][t] = {
            "macro_blocked": blocked,
            "macro_reason": (
                f"mkt_cap_bn={cap_bn:.0f}>{state['threshold_bn']:.0f}_{int(mktcap_frac*100)}pct_gdp"
                if blocked else f"mkt_cap_bn={cap_bn:.0f}_ok"
            ),
            "mkt_cap_bn": cap_bn,
        }
    return result
