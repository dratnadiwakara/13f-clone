"""EDGAR TTM cross-check of the quant screen for a quarter's HC names.

Informational only: it never changes the portfolio. run_quarter.py screens on
annual Compustat rows, which can be 12 to 18 months old. This re-runs the same
lib/screen.py flags on trailing-twelve-month (TTM) data from the latest
10-Q/10-K in SEC companyfacts and reports names whose pass/fail flips.

Each yearly point is TTM at the latest filing date, then the same date 1..5
years back. TTM = prior FY + current YTD - prior-year YTD. Balance-sheet items
are taken at those dates. Sector, SIC and mkvalt come from the Compustat row
in 01_screen.csv.

Approximations: special items (spi, xido) are 0; missing debt, capex and D&A
are 0; EBIT falls back to pretax income + interest when OperatingIncomeLoss is
not tagged; Compustat INTAN (which includes goodwill) is replicated. When
EDGAR cannot compute gm_3y or revt_cagr_3y (no COGS line, short US-GAAP
history) the Compustat value is used and listed under "Borrowed". Filers
without us-gaap facts (IFRS) are skipped. MF ranks are not recomputed.

    python refresh/edgar_ttm_check.py 2026Q3 [--tickers A,B,C]

Writes quarters/{Q}/07_edgar_check.csv and quarters/{Q}/07_edgar_check.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import screen as S  # noqa: E402
from refresh.refresh_fundamentals import USER_AGENT, _cik_for, _get  # noqa: E402

FLOW = {
    "revt": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
             "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
             "CostOfServices"],
    "ebit": ["OperatingIncomeLoss"],
    "dp": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "Depreciation"],
    "xint": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
             "InterestPaidNet"],
    "pi": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
           "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
           "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"],
    "txt": ["IncomeTaxExpenseBenefit"],
    "ni": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "nopi": ["OtherNonoperatingIncomeExpense"],
    "oancf": ["NetCashProvidedByUsedInOperatingActivities",
              "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capx": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
             "PaymentsToAcquireOtherPropertyPlantAndEquipment", "PaymentsForSoftware"],
    "epsfx": ["EarningsPerShareDiluted"],
}
INST = {
    "at": ["Assets"], "act": ["AssetsCurrent"], "lct": ["LiabilitiesCurrent"],
    "ppent": ["PropertyPlantAndEquipmentNet",
              "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    "intan": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "gdwl": ["Goodwill"], "invt": ["InventoryNet"],
    "rect": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "che": ["CashCashEquivalentsAndShortTermInvestments",
            "CashAndCashEquivalentsAtCarryingValue", "Cash"],
    "ceq": ["StockholdersEquity"],
    "seq": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "StockholdersEquity"],
    "mib": ["MinorityInterest"],
    "dltt": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
             "LongTermNotesPayable", "SeniorNotes"],
    "dlc": ["LongTermDebtCurrent", "DebtCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "stb": ["ShortTermBorrowings", "CommercialPaper"],
    "ivaeq": ["EquityMethodInvestments"],
    "dd1": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"],
    "dd2": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"],
}
TOL = pd.Timedelta(days=10)
KEY = ["revt_cagr_3y", "debt_ebitda", "intcov", "ni_clean_pct", "fcf_to_ni_3y",
       "roic_pre_3y", "roic_ex_gdwl", "gm_3y"]
FLAGS = ["pass_leverage", "pass_intcov", "pass_maturity_cliff", "pass_clean_earnings",
         "pass_loss_year", "pass_revenue", "pass_cash_conversion", "pass_franchise",
         "pass_quality_gate"]
BORROW = ["gm_3y", "revt_cagr_3y"]   # Compustat value when EDGAR cannot compute


# ---------- companyfacts -> TTM panel ----------

def facts_for(gaap, tag):
    u = gaap.get(tag, {}).get("units", {})
    if not u:
        return None
    unit = max(u, key=lambda k: len(u[k]))      # USD, CNY, USD/shares ...
    df = pd.DataFrame(u[unit])
    if df.empty or "end" not in df:
        return None
    df["end"] = pd.to_datetime(df["end"])
    if "start" in df:
        df["start"] = pd.to_datetime(df["start"])
    return df.sort_values("filed").drop_duplicates(
        [c for c in ("start", "end") if c in df], keep="last")


def near(df, col, when):
    m = df[(df[col] - when).abs() <= TOL]
    return m.iloc[(m[col] - when).abs().argmin()] if len(m) else None


def ttm(df, end):
    if df is None or "start" not in df:
        return np.nan
    df = df.assign(days=(df["end"] - df["start"]).dt.days)
    at_end = df[(df["end"] - end).abs() <= TOL]
    fy = at_end[at_end["days"].between(350, 380)]
    if len(fy):
        return float(fy.iloc[-1]["val"])
    ytd = at_end[at_end["days"] > 80].sort_values("days")
    prev_fy = df[df["days"].between(350, 380)]
    for _, y in ytd[::-1].iterrows():               # longest YTD first
        p = near(prev_fy, "end", y["start"] - pd.Timedelta(days=1))
        comp = df[(df["days"] - y["days"]).abs() <= 10]
        c = near(comp, "end", y["end"] - pd.DateOffset(years=1))
        if p is not None and c is not None:
            return float(p["val"] + y["val"] - c["val"])
    return np.nan


def inst(df, end):
    if df is None:
        return np.nan
    r = near(df, "end", end)
    return float(r["val"]) if r is not None else np.nan


def first(gaap, tags, fn, end):
    # Prefer the tag the filer uses now (latest end date), so a series does
    # not splice in a discontinued tag with partial coverage.
    def last_end(t):
        f = facts_for(gaap, t)
        return f["end"].max() if f is not None else pd.Timestamp(0)
    for t in sorted(tags, key=last_end, reverse=True):
        v = fn(facts_for(gaap, t), end)
        if pd.notna(v):
            return v
    return np.nan


def edgar_panel(ticker):
    cik = _cik_for(ticker)
    if cik is None:
        return None, "CIK not found"
    facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                 f"companyfacts_{ticker}.json")
    if not facts:
        return None, "companyfacts fetch failed"
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return None, "no us-gaap facts (IFRS filer?)"
    ends = []
    for t in FLOW["revt"] + FLOW["ni"]:
        f = facts_for(gaap, t)
        if f is not None and "form" in f:
            ends += list(f[f["form"].isin(["10-Q", "10-K", "20-F", "40-F"])]["end"])
    if not ends:
        return None, "no revenue/NI facts"
    latest = max(ends)
    rows = []
    for k in range(5, -1, -1):
        end = latest - pd.DateOffset(years=k)
        r = {"datadate": end}
        for c, tags in FLOW.items():
            r[c] = first(gaap, tags, ttm, end)
        for c, tags in INST.items():
            r[c] = first(gaap, tags, inst, end)
        rows.append(r)
    df = pd.DataFrame(rows)
    for c in df.columns:
        if c not in ("datadate", "epsfx"):
            df[c] = df[c] / 1e6                      # Compustat panel is in millions
    df["ebit"] = df["ebit"].fillna(df["pi"] + df["xint"].fillna(0))
    df["intan"] = df["intan"].fillna(0) + df["gdwl"].fillna(0)
    for c in ("nopi", "dltt", "mib", "ivaeq", "gdwl", "invt", "rect", "dp"):
        df[c] = df[c].fillna(0)
    df["capx"] = df["capx"].where(df["capx"].notna() | df["oancf"].isna(), 0.0)
    df["dlc"] = df["dlc"].fillna(0) + df["stb"].fillna(0)
    df["oiadp"] = df["ebit"]
    df["oibdp"] = df["ebitda"] = df["ebit"] + df["dp"]
    df["sale"] = df["revt"]
    df["wcap"] = df["act"] - df["lct"]
    for c in ("spi", "xido", "dptc", "dptb"):
        df[c] = 0.0
    return df.dropna(subset=["revt", "ni"], how="all"), latest.date().isoformat()


# ---------- screen ----------

def _true(v):
    return str(v) == "True"


def check(ticker, comp):
    df, latest = edgar_panel(ticker)
    if df is None:
        return {"ticker": ticker, "status": f"skipped: {latest}"}
    if df.empty:
        return {"ticker": ticker, "status": "skipped: no TTM revenue/NI could be built"}
    for c in ("gsector", "gind", "sic", "mkvalt", "indfmt"):
        df[c] = comp[c]
    m = S.per_gvkey_metrics(df, pd.Timestamp.today())
    borrowed = [k for k in BORROW if pd.isna(m.get(k)) and pd.notna(comp.get(k))]
    for k in borrowed:
        m[k] = comp[k]
    arche, _ = S.tag_archetype({**m, "ticker": ticker})
    row = {**m, "ticker": ticker, "archetype": arche}
    if arche in S.GATED_ARCHETYPES:
        row["quality_gate_passed"], row["quality_gate_reason"] = S.quality_gate(arche, m)
    fl = S.derive_flags(pd.Series(row))
    return {"ticker": ticker, "status": "ok", "edgar_latest": latest,
            "compustat_datadate": str(comp["datadate_used"])[:10],
            "archetype_compustat": comp["archetype"], "archetype_edgar": arche,
            "passes_compustat": _true(comp["passes_quant"]),
            "passes_edgar": bool(fl["passes_quant"]),
            "fails_compustat": ",".join(f for f in FLAGS if str(comp.get(f)) == "False"),
            "fails_edgar": ",".join(f for f in FLAGS if not fl[f]),
            "borrowed_from_compustat": ",".join(borrowed),
            **{f"comp_{k}": comp.get(k) for k in KEY},
            **{f"edgar_{k}": m.get(k) for k in KEY}}


def fmt(v):
    return "" if pd.isna(v) else f"{v:.2f}"


def write_md(res, q, path):
    ok = res[res["status"] == "ok"]
    flips = ok[ok["passes_compustat"] != ok["passes_edgar"]]
    lines = [
        f"# {q} EDGAR TTM check of the quant screen", "",
        "Informational. The portfolio uses the Compustat screen. This file re-runs the "
        "same flags on trailing-twelve-month EDGAR data (`refresh/edgar_ttm_check.py`; "
        "approximations are listed in its docstring). MF ranks are not recomputed.", "",
        f"Names checked: {len(res)}. Computed: {len(ok)}. Pass/fail flips: {len(flips)}"
        + (f" ({', '.join(flips['ticker'])})." if len(flips) else "."), "",
        "| Ticker | Compustat date | EDGAR TTM date | Compustat | EDGAR | EDGAR fails | Borrowed |",
        "|---|---|---|---|---|---|---|"]
    for r in res.itertuples():
        if r.status != "ok":
            lines.append(f"| {r.ticker} | | | | | {r.status} | |")
            continue
        flip = " (flip)" if r.passes_compustat != r.passes_edgar else ""
        lines.append(
            f"| {r.ticker} | {r.compustat_datadate} | {r.edgar_latest} | "
            f"{'PASS' if r.passes_compustat else 'FAIL'} | "
            f"{'PASS' if r.passes_edgar else 'FAIL'}{flip} | {r.fails_edgar} | "
            f"{r.borrowed_from_compustat} |")
    lines += ["", "## Key metrics (Compustat / EDGAR TTM)", "",
              "| Ticker | " + " | ".join(KEY) + " |", "|---" * (len(KEY) + 1) + "|"]
    for r in ok.itertuples():
        lines.append(f"| {r.ticker} | " + " | ".join(
            f"{fmt(getattr(r, 'comp_' + k))} / {fmt(getattr(r, 'edgar_' + k))}"
            for k in KEY) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("quarter")
    ap.add_argument("--tickers", default=None, help="comma list; default all HC names")
    a = ap.parse_args()
    if not USER_AGENT:
        sys.exit("[error] SEC_USER_AGENT is not set")
    outdir = REPO / "quarters" / a.quarter
    scr = pd.read_csv(outdir / "01_screen.csv", dtype={"gvkey": str, "cik": str},
                      low_memory=False).dropna(subset=["ticker"])
    # ETFs and depositories are never screened on fundamentals
    scr = scr[~scr["pass_etf_exclude"].astype(str).eq("False")
              & ~scr["pass_depository_exclude"].astype(str).eq("False")]
    comp = (scr[scr["gvkey"].notna()].sort_values("position_weight")
            .drop_duplicates("ticker", keep="last").set_index("ticker"))
    tickers = a.tickers.split(",") if a.tickers else sorted(comp.index)
    rows = []
    for t in tickers:
        if t not in comp.index:
            rows.append({"ticker": t, "status": "skipped: no Compustat row"})
        else:
            try:
                rows.append(check(t, comp.loc[t]))
            except Exception as e:           # one bad filer never stops the check
                rows.append({"ticker": t, "status": f"skipped: {type(e).__name__}: {e}"})
        r = rows[-1]
        msg = (f"Compustat {'PASS' if r['passes_compustat'] else 'FAIL'} -> "
               f"EDGAR {'PASS' if r['passes_edgar'] else 'FAIL'} {r['fails_edgar']}"
               if r["status"] == "ok" else r["status"])
        print(f"{t:6} {msg}")
    res = pd.DataFrame(rows)
    res.to_csv(outdir / "07_edgar_check.csv", index=False)
    write_md(res, a.quarter, outdir / "07_edgar_check.md")
    print(f"wrote {outdir / '07_edgar_check.md'}")


if __name__ == "__main__":
    main()
