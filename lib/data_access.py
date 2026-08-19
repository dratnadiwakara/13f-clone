"""Compustat duckdb wrappers. Reads path from config.yaml."""
from __future__ import annotations
from pathlib import Path
import time
import duckdb
import pandas as pd

from . import config


def _duckdb_path() -> Path:
    return config.path("compustat_duckdb")


def open_compustat():
    return duckdb.connect(str(_duckdb_path()), read_only=True)


def load_fund(cutoff: str | None = None,
              columns: list[str] | None = None,
              gvkeys: list[str] | None = None) -> pd.DataFrame:
    sel = "*" if not columns else ", ".join(f'"{c}"' for c in columns)
    where = []
    if cutoff:
        where.append(f"datadate <= DATE '{cutoff}'")
    if gvkeys:
        in_list = ",".join(f"'{g.zfill(6)}'" for g in gvkeys)
        where.append(f"LPAD(gvkey,6,'0') IN ({in_list})")
    sql = f"SELECT {sel} FROM compustat"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with open_compustat() as c:
        df = c.execute(sql).df()
    if "gvkey" in df.columns:
        df["gvkey"] = df["gvkey"].astype(str).str.zfill(6)
    if "datadate" in df.columns:
        df["datadate"] = pd.to_datetime(df["datadate"], errors="coerce")
    return df


def load_ratios(cutoff: str | None = None,
                gvkeys: list[str] | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM compustat_equity_ratios"
    where = []
    if cutoff:
        where.append(f"public_date <= TIMESTAMP '{cutoff}'")
    if gvkeys:
        in_list = ",".join(f"'{g.zfill(6)}'" for g in gvkeys)
        where.append(f"gvkey IN ({in_list})")
    if where:
        sql += " WHERE " + " AND ".join(where)
    with open_compustat() as c:
        df = c.execute(sql).df()
    if "public_date" in df.columns:
        df["public_date"] = pd.to_datetime(df["public_date"], errors="coerce")
    return df


def load_cusip_ticker_pit() -> pd.DataFrame:
    sql = """
        SELECT SUBSTR(cusip, 1, 8) AS cusip8,
               tic                 AS Ticker,
               datadate            AS MthCalDt
        FROM compustat
        WHERE cusip IS NOT NULL AND tic IS NOT NULL
        ORDER BY datadate
    """
    with open_compustat() as c:
        df = c.execute(sql).df()
    df["MthCalDt"] = pd.to_datetime(df["MthCalDt"], errors="coerce")
    return df


def load_compstat_for_actions(cutoff: str | None = None) -> pd.DataFrame:
    return load_fund(cutoff=cutoff, columns=["gvkey", "cusip", "datadate", "ni", "revt", "mkvalt", "tic"])


def load_ratios_live(as_of: pd.Timestamp,
                     mkt_cap_lookup: dict[str, float],
                     stale_days: int = 60) -> pd.DataFrame:
    r = load_ratios(cutoff=as_of.strftime("%Y-%m-%d"))
    r = r.sort_values(["gvkey", "public_date"]).copy()
    r["_is_latest"] = ~r.duplicated("gvkey", keep="last")
    r["days_stale"] = (as_of - r["public_date"]).dt.days
    r["mkt_cap_live"] = r["Ticker"].map(mkt_cap_lookup)
    refresh = (r["_is_latest"]
               & (r["days_stale"] > stale_days)
               & r["mkt_cap_live"].notna()
               & (r["ni_clean"] > 0))
    r["pe_op_dil_orig"] = r["pe_op_dil"]
    r.loc[refresh, "pe_op_dil"] = r.loc[refresh, "mkt_cap_live"] / r.loc[refresh, "ni_clean"]
    r["pe_refreshed"] = refresh
    return r


def fetch_mkt_caps(tickers: list[str], as_of: pd.Timestamp,
                   cache_dir: Path | None = None,
                   live_window_days: int = 7) -> dict[str, float]:
    """{ticker: market_cap_$M} at as_of. Live via yfinance fast_info if recent,
    else close * csho from compustat. Cached per as_of."""
    import yfinance as yf

    if cache_dir is not None:
        cache_file = cache_dir / f"mkt_caps_{as_of.strftime('%Y-%m-%d')}.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
            return dict(zip(df["Ticker"], df["mkt_cap_M"]))

    now = pd.Timestamp.today().normalize()
    is_live = abs((now - as_of).days) <= live_window_days
    out: dict[str, float] = {}

    if is_live:
        for t in tickers:
            try:
                tk = yf.Ticker(t.replace(".", "-"))
                try:
                    mc = tk.fast_info["market_cap"]
                except (KeyError, TypeError):
                    mc = None
                if mc:
                    out[t] = float(mc) / 1e6
            except Exception:
                continue
            time.sleep(0.05)
    else:
        yt_map = {t: t.replace(".", "-") for t in tickers}
        prices = yf.download(
            list(yt_map.values()),
            start=as_of - pd.Timedelta(days=10),
            end=as_of + pd.Timedelta(days=2),
            auto_adjust=True, progress=False, threads=True, group_by="ticker",
        )
        csho_df = load_fund(cutoff=as_of.strftime("%Y-%m-%d"),
                            columns=["gvkey", "datadate", "tic", "csho"])
        csho_df = csho_df.dropna(subset=["tic"]).sort_values("datadate").drop_duplicates("tic", keep="last")
        tic_to_csho = dict(zip(csho_df["tic"], csho_df["csho"]))
        for t in tickers:
            yt = yt_map[t]
            try:
                if isinstance(prices.columns, pd.MultiIndex):
                    if yt not in prices.columns.get_level_values(0):
                        continue
                    close = prices[yt]["Close"].dropna()
                else:
                    close = prices["Close"].dropna()
                if close.empty:
                    continue
                px = float(close.iloc[-1])
                csho = tic_to_csho.get(t)
                if not csho or csho <= 0:
                    continue
                out[t] = px * csho
            except Exception:
                continue

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"Ticker": list(out.keys()), "mkt_cap_M": list(out.values())}) \
            .to_parquet(cache_file, index=False)
    return out
