"""PIT active-filer test.

At cutoff C, include any candidate CIK with
  - >= `min_filings` filings in trailing `trailing_qtrs` quarters
  - >= `window_min` filings in trailing `window_qtrs` quarters
Purpose: remove survivorship bias — closed managers are restored, but truly
absent CIKs are dropped.
"""
from __future__ import annotations
import pandas as pd

from . import config, holdings as h_mod, managers


def _quarter_index(q: str) -> int:
    return int(q[:4]) * 4 + int(q[-1]) - 1


def _cutoff_to_qidx(c: str) -> int:
    ts = pd.Timestamp(c)
    qn = (ts.month - 1) // 3 + 1
    return ts.year * 4 + qn - 1


def build_universe(cutoff: str,
                   candidates: list[str] | None = None,
                   holdings_qtrs: pd.DataFrame | None = None,
                   provisional: list[str] | None = None) -> list[str]:
    cfg = config.load()["universe"]
    if candidates is None:
        candidates = managers.load_ciks()
    if holdings_qtrs is None:
        holdings_qtrs = h_mod._read_base(provisional, columns=["cik", "quarter"])

    qidx_cut = _cutoff_to_qidx(cutoff)
    h = holdings_qtrs[holdings_qtrs["cik"].isin(candidates)].copy()
    h["qidx"] = h["quarter"].map(_quarter_index)
    h = h[h["qidx"] <= qidx_cut]
    filings = h.drop_duplicates(["cik", "quarter"])[["cik", "qidx"]]

    trailing = cfg["active_filer_trailing_qtrs"]
    min_fil = cfg["active_filer_min_filings"]
    window = cfg["active_filer_window_qtrs"]
    win_min = cfg["active_filer_window_min"]

    cnt_trail = (
        filings[filings["qidx"] >= qidx_cut - (trailing - 1)]
        .groupby("cik").size()
    )
    cnt_window = (
        filings[filings["qidx"] >= qidx_cut - (window - 1)]
        .groupby("cik").size()
    )
    return [c for c in candidates
            if cnt_trail.get(c, 0) >= min_fil and cnt_window.get(c, 0) >= win_min]
