"""13F holdings loader with amendment dedup + discretion aggregation.

Amendment rule: for a given (cik, quarter, cusip), if any 13F-HR/A row exists
(form_type contains '/A' or amendment_flag=='Y'), drop all non-/A rows for
that group — treat /A as authoritative restatement. Then aggregate across
`investment_discretion` splits (SOLE vs SHARED) by summing value + shares.

Equity-only: put_call empty AND shares_or_prn_type == 'SH'.

Provisional quarters: `provisional=` accepts quarters SEC has not yet published
in bulk, sourced from individual EDGAR 13F-HR filings by
`materials/13f/fetch_13f_filings.py`. Sidecars are concatenated on read and are
never written back into the authoritative parquet.
"""
from __future__ import annotations
from pathlib import Path

import pandas as pd

from . import config


def provisional_path(quarter: str) -> Path:
    return config.path("provisional_dir") / f"13f_provisional_{quarter}.parquet"


def load_provisional(quarters: list[str]) -> pd.DataFrame:
    """Read provisional sidecars. Raises if a requested quarter has no sidecar."""
    frames: list[pd.DataFrame] = []
    for q in quarters:
        p = provisional_path(q)
        if not p.exists():
            raise FileNotFoundError(
                f"no provisional sidecar for {q} at {p}. Build it with:\n"
                f"  python materials/13f/fetch_13f_filings.py --quarter {q}"
            )
        frames.append(pd.read_parquet(p))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _read_base(provisional: list[str] | None,
               columns: list[str] | None = None) -> pd.DataFrame:
    """Authoritative parquet plus any provisional sidecars.

    A provisional quarter that has since been published in bulk is dropped from
    the sidecar side, so the authoritative rows always win.
    """
    df = pd.read_parquet(config.path("holdings_parquet"), columns=columns)
    if not provisional:
        return df
    extra = load_provisional(provisional)
    if columns is not None:
        extra = extra[columns]
    already = set(df["quarter"].unique()) if "quarter" in df.columns else set()
    overlap = sorted(set(provisional) & already)
    if overlap:
        extra = extra[~extra["quarter"].isin(overlap)]
    return pd.concat([df, extra], ignore_index=True) if len(extra) else df


def load_holdings(ciks: list[str] | None = None,
                  columns: list[str] | None = None,
                  provisional: list[str] | None = None) -> pd.DataFrame:
    """Return (cik, quarter, cusip) → value_thousands + shares + issuer_name."""
    df = _read_base(provisional)
    if ciks is not None:
        df = df[df["cik"].isin(ciks)]
    df = df.copy()
    df = df[df["shares_or_prn_type"] == "SH"]
    pc = df["put_call"].fillna("").astype(str).str.strip()
    df = df[pc == ""]

    df["amendment_flag"] = df["amendment_flag"].fillna("")
    if "form_type" in df.columns:
        df["_is_amend"] = df["form_type"].astype(str).str.contains("/A", na=False)
    else:
        df["_is_amend"] = df["amendment_flag"].astype(str).str.upper().eq("Y")

    grp_has_amend = df.groupby(["cik", "quarter", "cusip"])["_is_amend"].transform("any")
    df = df[(~grp_has_amend) | df["_is_amend"]].copy()
    df = df.drop_duplicates(
        ["cik", "quarter", "cusip", "investment_discretion"], keep="last"
    ).drop(columns=["_is_amend"])

    g = (
        df.groupby(["cik", "quarter", "cusip"], as_index=False)
        .agg(
            value_thousands=("value_thousands", "sum"),
            shares=("shares_or_prn_amount", "sum"),
            issuer_name=("issuer_name", "first"),
        )
    )
    return g


def latest_manager_names(ciks: list[str],
                         provisional: list[str] | None = None) -> dict[str, str]:
    df = _read_base(provisional, columns=["cik", "quarter", "manager_name"])
    df = df[df["cik"].isin(ciks)]
    df = df.sort_values(["cik", "quarter"]).drop_duplicates("cik", keep="last")
    return dict(zip(df["cik"], df["manager_name"]))
