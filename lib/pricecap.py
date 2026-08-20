"""Price-runup cap: skip candidates that have run away from the price at
which the tracked managers were buying.

runup = price(formation_date of q) / price(quarter_end of first_buy_quarter) - 1

first_buy_quarter is the earliest quarter inside the HC lookback window in
which a qualifying manager actually added to the name (lib/bands.add_hc_alt).
Where several managers hold a name, the earliest across them is used, so the
cap measures the move since the FIRST of them started buying.

Blocked when runup > price_cap.max_runup. Missing price history passes, in
line with the rest of the pipeline. Set price_cap.max_runup to null to
disable the stage entirely.

This is a behavioural constraint, not an alpha source — see
backtest/VARIANTS.md for the cost of each threshold.
"""
from __future__ import annotations

import time

import pandas as pd

from . import config, ranks


def _yf_close(ticker: str, start: pd.Timestamp, end: pd.Timestamp):
    """Daily closes for [start, end], or None on any failure."""
    import yfinance as yf
    try:
        h = yf.Ticker(ticker.replace(".", "-")).history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=5)).strftime("%Y-%m-%d"),
            auto_adjust=True)
    except Exception:
        return None
    if h is None or h.empty or "Close" not in h:
        return None
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s.sort_index()


def _asof(s, d: pd.Timestamp) -> float | None:
    if s is None or s.empty:
        return None
    prior = s[s.index <= d]
    return float(prior.iloc[-1]) if len(prior) else None


def evaluate(first_buy: dict[str, str], as_of: pd.Timestamp) -> dict[str, dict]:
    """{ticker: first_buy_quarter} -> {ticker: {runup, blocked, reason}}.

    Only the _by_ticker payload is returned (no shared state), so callers can
    merge it into the funnel the same way lib/macro.evaluate results are used.
    """
    max_runup = config.load().get("price_cap", {}).get("max_runup")
    out: dict[str, dict] = {}
    if max_runup is None:
        for t in first_buy:
            out[t] = {"runup": None, "blocked": False, "reason": "cap_disabled"}
        return out

    for t, fq in sorted(first_buy.items()):
        if not fq:
            out[t] = {"runup": None, "blocked": False, "reason": "no_purchase_in_window"}
            continue
        basis_date = ranks.quarter_end(fq)
        s = _yf_close(t, basis_date - pd.Timedelta(days=10), as_of)
        p_then, p_now = _asof(s, basis_date), _asof(s, as_of)
        if not p_then or not p_now or p_then <= 0:
            out[t] = {"runup": None, "blocked": False, "reason": "no_price_history"}
            continue
        runup = p_now / p_then - 1.0
        blocked = runup > max_runup
        out[t] = {
            "runup": runup,
            "blocked": blocked,
            "reason": (f"runup {runup:+.0%} since {fq} > {max_runup:+.0%}" if blocked
                       else f"runup {runup:+.0%} since {fq}"),
        }
        time.sleep(0.05)
    return out
