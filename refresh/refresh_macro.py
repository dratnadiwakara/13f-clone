"""Refresh macro inputs for the mega-cap gate.

GDP: FRED `GDP` series (nominal, $bn, quarterly), API key from
C:/key-variables/key-variables.yaml -> api_keys.fred.
S&P 500 trailing PE: scraped from multpl.com's current-value page.
Both upsert into data/macro/{gdp,sp_pe}.parquet (schemas expected by
lib/macro.py: date+gdp_bn, date+sp_pe_ttm). Network failures leave the
existing parquets untouched — the run continues on stale macro with a warning.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[1]
GDP_PQ = REPO / "data/macro/gdp.parquet"
PE_PQ = REPO / "data/macro/sp_pe.parquet"
KEYS = Path("C:/key-variables/key-variables.yaml")
UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "investments-research/1.0")}


def fred_key() -> str | None:
    try:
        import yaml
        return yaml.safe_load(KEYS.read_text())["api_keys"]["fred"]
    except Exception:
        return None


def refresh_gdp() -> None:
    key = fred_key()
    if not key:
        print("[macro] no FRED key — GDP left as-is")
        return
    try:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": "GDP", "api_key": key,
                                 "file_type": "json", "observation_start": "2015-01-01"},
                         timeout=60)
        obs = r.json()["observations"]
    except Exception as e:
        print(f"[macro] FRED fetch failed ({e}) — GDP left as-is")
        return
    fresh = pd.DataFrame({"date": pd.to_datetime([o["date"] for o in obs]),
                          "gdp_bn": [float(o["value"]) for o in obs if o["value"] != "."]})
    # FRED dates the quarter start; macro.py wants as-of dates — shift to quarter end
    fresh["date"] = fresh["date"] + pd.offsets.QuarterEnd(0)
    old = pd.read_parquet(GDP_PQ)
    out = (pd.concat([old, fresh]).drop_duplicates("date", keep="last")
           .sort_values("date").reset_index(drop=True))
    out.to_parquet(GDP_PQ, index=False)
    print(f"[macro] GDP -> {out['date'].max().date()} (${out['gdp_bn'].iloc[-1]:,.0f}bn)")


def refresh_sp_pe() -> None:
    try:
        html = requests.get("https://www.multpl.com/s-p-500-pe-ratio", headers=UA,
                            timeout=60).text
        m = re.search(r"Current S&P 500 PE Ratio[^0-9]*([0-9]+\.[0-9]+)", html)
        if not m:
            m = re.search(r'id="current"[^>]*>[^0-9]*([0-9]+\.[0-9]+)', html, re.S)
        pe = float(m.group(1))
    except Exception as e:
        print(f"[macro] multpl scrape failed ({e}) — S&P PE left as-is")
        return
    today = pd.Timestamp.today().normalize()
    old = pd.read_parquet(PE_PQ)
    out = (pd.concat([old, pd.DataFrame({"date": [today], "sp_pe_ttm": [pe]})])
           .drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True))
    out.to_parquet(PE_PQ, index=False)
    print(f"[macro] S&P PE -> {pe} @ {today.date()}")


if __name__ == "__main__":
    refresh_gdp()
    refresh_sp_pe()
