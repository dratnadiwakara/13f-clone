"""EDGAR companyfacts patch for stale Compustat fundamentals.

For an HC candidate whose latest Compustat datadate is older than
fundamentals.stale_days at the cutoff, pull SEC companyfacts.json, recompute
earnings yield and return on capital from the latest 10-K/20-F annual facts,
and re-locate the name's percentile inside the quarter's existing rank
distribution (lib.ranks.locate_pct) — the universe is never rebuilt.

Filers without usable US-GAAP tags (pure IFRS taxonomies) fall back to the
Compustat row: returns None with reason, never raises.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
CACHE = REPO / "data" / "cache" / "edgar"
# SEC requires a contact address in the User-Agent; read from SEC_USER_AGENT.
USER_AGENT = os.environ.get("SEC_USER_AGENT", "")
TTL_SEC = 24 * 3600

EBIT_TAGS = ["OperatingIncomeLoss"]
TAGS = {
    "assets_current": ["AssetsCurrent"],
    "liab_current": ["LiabilitiesCurrent"],
    "ppent": ["PropertyPlantAndEquipmentNet"],
    "ltd": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "debt_current": ["DebtCurrent", "LongTermDebtCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "Cash"],
    "minority": ["MinorityInterest"],
}


def _get(url: str, cache_name: str) -> dict | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / cache_name
    if f.exists() and time.time() - f.stat().st_mtime < TTL_SEC:
        return json.loads(f.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    f.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(0.12)
    return data


def _cik_for(ticker: str) -> str | None:
    data = _get("https://www.sec.gov/files/company_tickers.json", "company_tickers.json")
    if not data:
        return None
    t = ticker.upper().replace("-", ".")
    for row in data.values():
        if row.get("ticker", "").upper() in (t, ticker.upper()):
            return str(row["cik_str"]).zfill(10)
    return None


def _latest_annual(facts: dict, tags: list[str]) -> tuple[float | None, str | None]:
    """Latest FY value (10-K or 20-F) in USD for the first tag that has one."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {}).get("USD", [])
        annual = [u for u in units
                  if u.get("form") in ("10-K", "20-F") and u.get("fp") == "FY"
                  and u.get("val") is not None]
        if annual:
            best = max(annual, key=lambda u: (u.get("end", ""), u.get("filed", "")))
            return float(best["val"]), best.get("end")
    return None, None


def fetch_fresh_metrics(ticker: str, mkt_cap_musd: float | None) -> dict:
    """Returns {ok, ey, roc, end_date, reason}. mkt_cap_musd from yfinance
    (caller supplies via lib.data_access.fetch_mkt_caps)."""
    out = {"ok": False, "ticker": ticker, "reason": None,
           "ey": None, "roc": None, "end_date": None}
    cik = _cik_for(ticker)
    if cik is None:
        out["reason"] = "cik_unresolved"
        return out
    facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                 f"companyfacts_{ticker}.json")
    if not facts:
        out["reason"] = "companyfacts_fetch_failed"
        return out

    ebit, end = _latest_annual(facts, EBIT_TAGS)
    if ebit is None:
        out["reason"] = "no_usgaap_ebit (IFRS filer?) — edgar_fallback=compustat_row"
        return out
    vals = {k: _latest_annual(facts, tags)[0] for k, tags in TAGS.items()}
    if mkt_cap_musd is None or pd.isna(mkt_cap_musd):
        out["reason"] = "no_live_mkt_cap"
        return out

    musd = 1e6  # XBRL values are dollars; Compustat panel is $M
    ev = (mkt_cap_musd
          + (vals["ltd"] or 0) / musd + (vals["debt_current"] or 0) / musd
          + (vals["minority"] or 0) / musd - (vals["cash"] or 0) / musd)
    nwc = None
    if vals["assets_current"] is not None and vals["liab_current"] is not None:
        nwc = vals["assets_current"] - vals["liab_current"]
    cap_employed = max(nwc or 0, 0) / musd + (vals["ppent"] or 0) / musd

    ebit_m = ebit / musd
    if ev <= 0 or cap_employed <= 0:
        out["reason"] = f"nonpositive ev/cap (ev={ev:.0f}, ce={cap_employed:.0f})"
        return out
    out.update(ok=True, ey=ebit_m / ev, roc=ebit_m / cap_employed, end_date=end)
    return out
