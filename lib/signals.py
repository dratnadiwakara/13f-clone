"""Detect new positions and significant adds from 13F holdings.

Keep = action == 'new' OR incremental_weight > add_dollar_weight OR
       shares/shares_prev >= add_shares_ratio.

Gap handling: if manager didn't file at prev_q, drop the row (can't tell
new vs continuation). Mid-quarter price cache overrides EoQ MV pro-rata
when present.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from . import config


def quarter_end_date(q: str) -> pd.Timestamp:
    y = int(q[:4])
    qn = int(q[-1])
    month, day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[qn]
    return pd.Timestamp(year=y, month=month, day=day)


def prev_quarter(q: str) -> str:
    y, qn = int(q[:4]), int(q[-1])
    return f"{y - 1}Q4" if qn == 1 else f"{y}Q{qn - 1}"


def load_mid_qtr_prices(cache_pq: Path | None) -> dict[tuple[str, str], float]:
    if cache_pq is None or not cache_pq.exists():
        return {}
    p = pd.read_parquet(cache_pq)
    return {(r.cusip, r.quarter): r.mid_price for r in p.itertuples()}


def build_actions(holdings: pd.DataFrame,
                  start_quarter: str | None = None,
                  mid_prices: dict | None = None) -> pd.DataFrame:
    cfg = config.load()["signal_thresholds"]
    if start_quarter is None:
        start_quarter = cfg["start_quarter"]
    if mid_prices is None:
        mid_prices = {}
    add_wt = cfg["add_dollar_weight"]
    shares_ratio = cfg["add_shares_ratio"]

    quarters = sorted(holdings["quarter"].unique())
    target_quarters = [q for q in quarters if q >= start_quarter]
    active = holdings.groupby(["cik", "quarter"]).size().reset_index(name="_n")
    active_set = set(zip(active["cik"], active["quarter"]))

    rows: list[pd.DataFrame] = []
    for q in target_quarters:
        cur = holdings[holdings["quarter"] == q].copy()
        prev_q = prev_quarter(q)
        prev_full = holdings[holdings["quarter"] == prev_q]
        prev = prev_full[["cik", "cusip", "shares"]]
        prev = prev.rename(columns={"shares": "shares_prev"})

        # Median implied EOQ price per cusip (value/shares, same for every
        # filer up to reporting noise) — a stock property, so it detects
        # splits even with a single holder: buying doesn't move the
        # per-share price, a split divides it by exactly the factor.
        def _px(frame):
            f = frame[frame["shares"] > 0]
            return (f["value_thousands"] / f["shares"]).groupby(f["cusip"]).median()
        px_cur = _px(cur)
        px_prev = _px(prev_full)

        merged = cur.merge(prev, on=["cik", "cusip"], how="left")
        merged["_prev_filed"] = merged["cik"].apply(
            lambda c: (c, prev_q) in active_set
        )
        merged["shares_prev"] = merged["shares_prev"].fillna(0)

        # Split adjustment: a stock split multiplies every holder's share
        # count by the same factor, which raw QoQ deltas misread as massive
        # purchases (e.g. CVNA 5:1 in 2026Q2). Two detectors, both gated on
        # a share ratio outside (0.71, 1.4):
        #   1. Cross-holder cluster: >= 2 holders at the same ratio (within
        #      2%) — non-traders sit exactly at the split factor. Implied
        #      price must not contradict (loose gate; price also moves with
        #      the market).
        #   2. Single holder: only for factors >= 2x (below that, a big buy
        #      plus ordinary market drift can mimic the price signature —
        #      e.g. a genuine 1.42x SPGI add was misflagged before this
        #      gate), and the implied-price ratio must CONFIRM the share
        #      ratio within ~33% — a genuine buy leaves the per-share price
        #      unchanged, a split moves it reciprocally.
        cont = merged[merged["shares_prev"] > 0]
        for cusip, g in cont.groupby("cusip"):
            r = (g["shares"] / g["shares_prev"]).sort_values()
            med = r.median()
            if 0.71 < med < 1.4:
                continue
            pr = (px_prev.get(cusip, np.nan) / px_cur.get(cusip, np.nan))
            factor = None
            at_factor = r[(r / med - 1).abs() < 0.02]
            if len(at_factor) >= 2:
                f = at_factor.median()
                if not (pr == pr) or 0.5 <= pr / f <= 2.0:
                    factor = f
            elif (len(g) == 1 and (med >= 2.0 or med <= 0.5)
                  and pr == pr and 0.75 <= pr / med <= 1.33):
                factor = med
            if factor is not None:
                mask = (merged["cusip"] == cusip) & (merged["shares_prev"] > 0)
                merged.loc[mask, "shares_prev"] *= factor

        is_new = (merged["shares_prev"] == 0) & merged["_prev_filed"]
        is_add = (~is_new) & merged["_prev_filed"] & (merged["shares"] > merged["shares_prev"])
        merged = merged[is_new | is_add].copy()
        merged["action"] = np.where(merged["shares_prev"] == 0, "new", "add")

        port = (
            cur.groupby("cik", as_index=False)["value_thousands"]
            .sum()
            .rename(columns={"value_thousands": "portfolio_value_thousands"})
        )
        merged = merged.merge(port, on="cik", how="left")

        delta_shares = merged["shares"] - merged["shares_prev"]
        if mid_prices:
            mp = merged.apply(lambda r: mid_prices.get((r["cusip"], q)), axis=1)
            merged["mid_price"] = mp
            inc_dollar = delta_shares * mp / 1000.0
            fallback = merged["value_thousands"] * delta_shares / merged["shares"]
            merged["incremental_value_thousands"] = inc_dollar.fillna(fallback)
            merged["price_source"] = np.where(mp.notna(), "mid_qtr", "eoq_mv_fallback")
        else:
            merged["incremental_value_thousands"] = (
                merged["value_thousands"] * delta_shares / merged["shares"]
            )
            merged["price_source"] = "eoq_mv_fallback"

        merged["position_weight"] = (
            merged["value_thousands"] / merged["portfolio_value_thousands"]
        )
        merged["incremental_weight"] = (
            merged["incremental_value_thousands"] / merged["portfolio_value_thousands"]
        )

        ratio = np.where(
            merged["shares_prev"] > 0,
            merged["shares"] / merged["shares_prev"].replace(0, np.nan),
            0.0,
        )
        keep = (merged["action"] == "new") | (
            (merged["incremental_weight"] > add_wt)
            | (ratio >= shares_ratio)
        )
        merged = merged[keep].copy()
        merged["shares_prev"] = merged["shares_prev"].astype(float)
        merged = merged.drop(columns=["_prev_filed"], errors="ignore")
        rows.append(merged)

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def resolve_tickers(actions: pd.DataFrame, cw: pd.DataFrame,
                    comp: pd.DataFrame, offline: bool = False) -> pd.DataFrame:
    """Attach tickers: OpenFIGI first, then the Compustat PIT cusip8→Ticker
    lookup, then compustat tic. The Compustat steps only fill CUSIPs OpenFIGI
    cannot map (mostly retired CUSIPs in older quarters). `ticker_source`
    records which step supplied each ticker."""
    from . import openfigi
    actions = actions.copy()
    actions["cusip8"] = actions["cusip"].astype(str).str[:8]
    actions["quarter_end"] = actions["quarter"].map(quarter_end_date)
    actions["quarter_end_ts"] = actions["quarter_end"]

    cusip9 = actions["cusip"].astype(str).str.strip().str.upper().str.zfill(9)
    figi = openfigi.cusip_to_ticker(cusip9.unique(), offline=offline)
    actions["ticker"] = cusip9.map(figi).astype(object)
    actions["ticker_source"] = pd.Series(
        np.where(actions["ticker"].notna(), "openfigi", None), index=actions.index, dtype=object)

    tickers = []
    for (cu, qe), grp in actions[actions["ticker"].isna()].groupby(
            ["cusip8", "quarter_end_ts"], sort=False):
        g = cw[(cw["cusip8"] == cu) & (cw["MthCalDt"] <= qe)]
        t = g.iloc[-1]["Ticker"] if not g.empty else None
        for idx in grp.index:
            tickers.append((idx, t))
    tdf = pd.DataFrame(tickers, columns=["_idx", "ticker"]).set_index("_idx")
    if len(tdf):
        fill = tdf["ticker"].dropna()
        actions.loc[fill.index, "ticker"] = fill
        actions.loc[fill.index, "ticker_source"] = "compustat_pit"
    actions = actions.drop(columns=["quarter_end_ts"])

    if "cusip" in comp.columns:
        comp = comp.copy()
        comp["cusip8"] = comp["cusip"].astype(str).str.strip().str.zfill(9).str[:8]
    comp_tic = (
        comp.dropna(subset=["tic"])
        .sort_values("datadate")
        .drop_duplicates("cusip8", keep="last")
        .set_index("cusip8")["tic"]
    )
    miss = actions["ticker"].isna()
    actions.loc[miss, "ticker"] = actions.loc[miss, "cusip8"].map(comp_tic)
    actions.loc[miss & actions["ticker"].notna(), "ticker_source"] = "compustat_tic"
    return actions
