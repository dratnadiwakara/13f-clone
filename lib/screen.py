"""Fundamentals screen: per-row Compustat metrics + archetype + passes_quant.

Ports V2 `validation/01-screen/run_screen.py` metric path plus
`implementation/lib/selection.py` flag derivation. Drops the LLM verdict
tier layer (AUTO_BUY / REVIEW / PARKED_LLM_ONLY / AUTO_PASS) — this module
emits raw metrics + `passes_quant` boolean only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from . import config, data_access as da

CYCLICAL_SIC_PREFIXES = (
    "10", "12", "13", "14", "15", "16", "24", "26", "29", "33",
    "1520", "1531", "2911", "3310", "3312", "3316", "3317",
    "3334", "3674", "4412", "4400",
)


def _hard_excludes() -> tuple[set, set]:
    hx = config.load()["hard_excludes"]
    return set(hx["depositories"]), set(hx["etfs"])


def safe_div(a, b):
    return np.where((b == 0) | pd.isna(b) | pd.isna(a), np.nan, a / b)


def cagr(series: pd.Series, years: int) -> float:
    s = series.dropna()
    if len(s) < years + 1:
        return np.nan
    start, end = s.iloc[-(years + 1)], s.iloc[-1]
    if start <= 0 or pd.isna(start) or pd.isna(end):
        return np.nan
    return (end / start) ** (1 / years) - 1


def slope(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 3:
        return np.nan
    x = np.arange(len(s))
    return np.polyfit(x, s.values, 1)[0]


def is_cyclical_sic(sic) -> bool:
    if pd.isna(sic):
        return False
    s = str(int(sic)).zfill(4) if isinstance(sic, (int, float)) else str(sic).strip()
    return any(s.startswith(p) for p in CYCLICAL_SIC_PREFIXES)


def tag_archetype(row) -> tuple[str, str]:
    depositories, _ = _hard_excludes()
    at = row.get("at")
    if pd.isna(at) or at == 0:
        return "unclear", "missing_at"
    gs_raw = row.get("gsector")
    gsector = str(int(float(gs_raw))) if pd.notna(gs_raw) else ""
    sic = row.get("sic")
    ticker = row.get("ticker", "")
    sic_int = int(float(sic)) if pd.notna(sic) else 0
    if ticker in depositories:
        return "bank", "ticker_depository_exclude"
    if 6020 <= sic_int <= 6036 or sic_int == 6712:
        return "bank", f"sic_{sic_int}_depository"
    dptc = row.get("dptc") or 0
    dptb = row.get("dptb") or 0
    if at and (dptc + dptb) / at > 0.30:
        return "bank", "deposits_dominant"
    if gsector == "55":
        return "utility-regulated", "gsector_utility"
    if gsector == "60":
        return "reit", "gsector_reit"
    if is_cyclical_sic(sic):
        return "cyclical", f"sic_{sic}_cyclical"
    ivaeq = row.get("ivaeq") or 0
    if ivaeq / at > 0.25:
        return "holdco-conglomerate", "associates_25pct"
    intan = row.get("intan") or 0
    gdwl = row.get("gdwl") or 0
    ppent = row.get("ppent") or 0
    if (intan + gdwl) / at > 0.40 and ppent / at < 0.20:
        return "asset-light", "intangible_dominant"
    invt = row.get("invt") or 0
    rect = row.get("rect") or 0
    if (ppent + invt + rect) / at > 0.40:
        return "trad-ops", "tangible_operating"
    return "unclear", "no_archetype_match"


def per_gvkey_metrics(g: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    g = g[g["datadate"] <= as_of].sort_values("datadate")
    if g.empty:
        return {"_missing": True}
    out = {"_missing": False}
    last = g.iloc[-1]
    out["datadate_used"] = last["datadate"]
    out["fyear"] = last.get("fyear")

    for c in ["gsector", "gind", "sic", "indfmt", "at", "dptc", "dptb",
              "ivaeq", "intan", "gdwl", "ppent", "invt", "rect", "che",
              "act", "lct", "wcap",
              "seq", "ceq", "ceqt", "mib", "dltt", "dlc", "dt",
              "dd1", "dd2", "ni", "ib", "revt", "sale", "cogs", "xsga",
              "oibdp", "oiadp", "ebit", "ebitda", "dp", "xint", "pi", "txt",
              "xido", "spi", "nopi", "xrd", "epsfx", "csho", "mkvalt",
              "oancf", "capx", "prstkc", "sstk", "dvc", "dvt",
              "dltis", "dltr", "prcc_f"]:
        out[c] = last.get(c)

    ni = last.get("ni") or 0
    spi = last.get("spi") or 0
    nopi = last.get("nopi") or 0
    xido = last.get("xido") or 0
    ni_clean = ni - spi - nopi - xido
    out["ni_clean"] = ni_clean
    out["ni_clean_pct"] = safe_div(ni_clean, ni) if (ni and ni > 0) else np.nan
    out["spi_pct_ni"] = safe_div(spi, ni) if ni else np.nan

    revt = last.get("revt") or last.get("sale")
    out["gm"] = safe_div((revt or 0) - (last.get("cogs") or 0), revt) if revt else np.nan
    out["opmad"] = safe_div(last.get("oiadp"), revt) if revt else np.nan
    out["ebit_margin"] = safe_div(last.get("ebit"), revt) if revt else np.nan
    out["ni_margin"] = safe_div(ni, revt) if revt else np.nan

    def series(col):
        return g[col].astype(float)
    revt_s = series("revt").fillna(series("sale"))
    ni_s = series("ni")
    eps_s = series("epsfx")
    gm_s = (revt_s - series("cogs")) / revt_s
    opm_s = series("oiadp") / revt_s
    roa_s = series("ni") / series("at")
    fcf_s = series("oancf") - series("capx")

    out["gm_3y"] = gm_s.tail(3).mean()
    out["opmad_3y"] = opm_s.tail(3).mean()
    out["roa_3y"] = roa_s.tail(3).mean()
    out["gm_5y"] = gm_s.tail(5).mean()
    out["opmad_5y"] = opm_s.tail(5).mean()
    out["roa_5y"] = roa_s.tail(5).mean()
    out["ni_5y_avg"] = ni_s.tail(5).mean()
    out["gm_5y_slope"] = slope(gm_s.tail(5))
    out["opmad_5y_slope"] = slope(opm_s.tail(5))
    out["roa_5y_slope"] = slope(roa_s.tail(5))

    out["revt_cagr_3y"] = cagr(revt_s, 3)
    out["revt_cagr_5y"] = cagr(revt_s, 5)
    out["ni_cagr_5y"] = cagr(ni_s, 5)
    out["epsfx_cagr_5y"] = cagr(eps_s, 5)
    out["eps_ni_cagr_gap"] = (
        out["epsfx_cagr_5y"] - out["ni_cagr_5y"]
        if (pd.notna(out["epsfx_cagr_5y"]) and pd.notna(out["ni_cagr_5y"])) else np.nan
    )

    yoy = revt_s.pct_change().tail(5)
    out["revt_min_yoy_5y"] = yoy.min() if len(yoy) else np.nan

    fcf = fcf_s.iloc[-1] if len(fcf_s) else np.nan
    out["fcf"] = fcf
    out["fcf_3y_avg"] = fcf_s.tail(3).mean()
    out["fcf_to_ni_3y"] = safe_div(fcf_s.tail(3).mean(), ni_s.tail(3).mean())
    out["capex_to_sales_3y"] = safe_div(series("capx").tail(3).mean(), revt_s.tail(3).mean())

    ebit = last.get("ebit") or 0
    txt = last.get("txt") or 0
    pi_ = last.get("pi") or 0
    eff_tax = safe_div(txt, pi_) if pi_ else np.nan
    out["efftax"] = eff_tax
    nopat = ebit * (1 - (eff_tax if pd.notna(eff_tax) and 0 < eff_tax < 1 else 0.21))
    ceq_v = last.get("ceq") or 0
    dltt_v = last.get("dltt") or 0
    dlc_v = last.get("dlc") or 0
    che_v = last.get("che") or 0
    inv_cap = dltt_v + dlc_v + ceq_v - che_v
    out["roic_post_tax"] = safe_div(nopat, inv_cap) if inv_cap > 0 else np.nan
    out["roic_pre_tax"] = safe_div(ebit, inv_cap) if inv_cap > 0 else np.nan
    inv_cap_tangible = dltt_v + dlc_v + ceq_v
    out["roic_pre_tangible"] = safe_div(ebit, inv_cap_tangible) if inv_cap_tangible > 0 else np.nan
    gdwl_v = last.get("gdwl") or 0
    inv_cap_ex_gw = inv_cap - gdwl_v
    out["roic_ex_gdwl"] = safe_div(nopat, inv_cap_ex_gw) if inv_cap_ex_gw > 0 else np.nan

    ebit_s = series("ebit")
    cap_s = series("dltt") + series("dlc") + series("ceq") - series("che")
    cap_tangible_s = series("dltt") + series("dlc") + series("ceq")
    out["roic_pre_3y"] = (ebit_s / cap_s).tail(3).mean()
    out["roic_pre_tangible_3y"] = (ebit_s / cap_tangible_s).tail(3).mean()
    out["roa_3y_avg"] = roa_s.tail(3).mean()

    # Cash-free return on capital, identical to lib/ranks.roc. Used to gate
    # the "unclear" bucket, whose balance sheets are mostly cash: the standard
    # roic_pre_* denominator subtracts cash and collapses toward zero there.
    ebit_use = last.get("ebit")
    if pd.isna(ebit_use) or ebit_use is None:
        ebit_use = last.get("oiadp")
    act_v, lct_v = last.get("act"), last.get("lct")
    nwc = (act_v - lct_v) if (pd.notna(act_v) and pd.notna(lct_v)) else last.get("wcap")
    cap_emp = (0 if pd.isna(nwc) or nwc is None else max(float(nwc), 0.0)) + (last.get("ppent") or 0)
    out["cap_employed"] = cap_emp
    out["roc_gb"] = (safe_div(ebit_use, cap_emp)
                     if (cap_emp > 0 and pd.notna(ebit_use)) else np.nan)

    # Mid-cycle economics: a spot ROIC on a cyclical measures where the cycle
    # is, not business quality. 5y mean + count of profitable years instead.
    out["roic_pre_5y"] = (ebit_s / cap_s).tail(5).mean()
    ebit_tail = ebit_s.tail(5).dropna()
    out["ebit_pos_yrs_5y"] = float((ebit_tail > 0).sum()) if len(ebit_tail) else np.nan
    out["ebit_yrs_5y"] = float(len(ebit_tail))

    ebitda_v = last.get("ebitda") or last.get("oibdp") or 0
    net_debt = dltt_v + dlc_v - che_v
    out["net_debt"] = net_debt
    out["debt_ebitda"] = safe_div(net_debt, ebitda_v) if ebitda_v else np.nan
    xint_v = last.get("xint") or 0
    out["intcov"] = safe_div(ebit, xint_v) if xint_v else np.nan
    mkvalt_v = last.get("mkvalt") or 0
    dd1_dd2 = (last.get("dd1") or 0) + (last.get("dd2") or 0)
    out["maturity_cliff_2y"] = safe_div(dd1_dd2, mkvalt_v) if mkvalt_v else np.nan

    seq_v = last.get("seq") or 0
    mib_v = last.get("mib") or 0
    out["nci_share"] = safe_div(mib_v, seq_v + mib_v) if (seq_v + mib_v) else np.nan

    out["pe_fund"] = safe_div(mkvalt_v, ni)
    out["pe_clean_fund"] = safe_div(mkvalt_v, ni_clean) if ni_clean else np.nan
    out["ps_fund"] = safe_div(mkvalt_v, revt)
    ev = mkvalt_v + dltt_v + dlc_v + mib_v - che_v
    out["ev_ebit"] = safe_div(ev, ebit) if ebit else np.nan
    out["ev_ebitda"] = safe_div(ev, ebitda_v) if ebitda_v else np.nan
    out["fcf_yield_fund"] = safe_div(fcf, mkvalt_v) if mkvalt_v else np.nan

    at_v = last.get("at") or 0
    if at_v:
        out["pct_ppe"] = safe_div(last.get("ppent"), at_v)
        out["pct_intan"] = safe_div(last.get("intan"), at_v)
        out["pct_gdwl"] = safe_div(last.get("gdwl"), at_v)
        out["pct_associates"] = safe_div(last.get("ivaeq"), at_v)
        out["pct_deposits"] = safe_div((last.get("dptc") or 0) + (last.get("dptb") or 0), at_v)
        out["pct_op_assets"] = safe_div((last.get("ppent") or 0) + (last.get("invt") or 0) + (last.get("rect") or 0), at_v)

    return out


GATED_ARCHETYPES = ("trad-ops", "asset-light", "unclear", "cyclical")


def _gate_cfg(arche: str) -> dict:
    return config.load().get("quality_gate", {}).get(arche, {})


def quality_gate(arche: str, m: dict) -> tuple[bool | None, str]:
    """Archetype-appropriate return-on-capital hurdle.

    trad-ops / asset-light: original 2026-08 gate, missing data FAILS.
    unclear / cyclical: added 2026-08. Missing data PASSES (returns None),
    matching the rest of derive_flags; these buckets have thinner Compustat
    coverage and a data-completeness filter is not what is wanted here.
    None from any branch means "not evaluated" and derive_flags treats it as
    a pass.
    """
    if arche == "unclear":
        cfg = _gate_cfg("unclear")
        if not cfg.get("enabled", False):
            return None, "unclear_gate_disabled"
        # Cash-heavy balance sheets: return on OPERATING capital (cash excluded
        # from the denominator rather than netted out of it), plus a liveness
        # test so a biotech burning its cash pile does not read as high-return.
        roc = m.get("roc_gb")
        fcf = m.get("fcf_3y_avg")
        if pd.isna(roc):
            return None, "unclear_no_roc_gb"
        if roc < cfg["min_roc"]:
            return False, f"roc_gb_{roc:.2f}<{cfg['min_roc']}"
        if pd.notna(fcf) and fcf < cfg["min_fcf_3y_avg"]:
            return False, f"fcf3y_{fcf:.0f}<{cfg['min_fcf_3y_avg']}"
        return True, f"roc_gb_{roc:.2f}"
    if arche == "cyclical":
        cfg = _gate_cfg("cyclical")
        if not cfg.get("enabled", False):
            return None, "cyclical_gate_disabled"
        # Survivability + mid-cycle economics, not spot profitability.
        pos, yrs = m.get("ebit_pos_yrs_5y"), m.get("ebit_yrs_5y")
        r5 = m.get("roic_pre_5y")
        lev = m.get("debt_ebitda")
        if pd.notna(pos) and pd.notna(yrs) and yrs >= cfg["min_years"]                 and pos < cfg["min_profitable_yrs"]:
            return False, f"ebit_pos_{pos:.0f}of{yrs:.0f}<{cfg['min_profitable_yrs']}"
        if pd.notna(r5) and r5 < cfg["min_roic_5y"]:
            return False, f"roic5y_{r5:.2f}<{cfg['min_roic_5y']}"
        if pd.notna(lev) and lev > cfg["max_debt_ebitda"]:
            return False, f"debt_ebitda_{lev:.1f}>{cfg['max_debt_ebitda']}"
        if pd.isna(r5) and pd.isna(pos):
            return None, "cyclical_no_data"
        return True, f"roic5y_{r5:.2f}" if pd.notna(r5) else "cyclical_pass"
    if arche == "trad-ops":
        r = m.get("roic_pre_3y")
        if pd.isna(r):
            return False, "no_roic_data"
        if r < 0.15:
            return False, f"roic_pre_{r:.2f}<0.15"
        return True, f"roic_pre_{r:.2f}"
    if arche == "asset-light":
        roic = m.get("roic_ex_gdwl")
        gm3 = m.get("gm_3y")
        if pd.isna(roic) or pd.isna(gm3):
            return False, "no_roic_or_gm"
        if roic < 0.20 or gm3 < 0.40:
            return False, f"roic_ex_gw_{roic:.2f}_gm_{gm3:.2f}"
        return True, f"roic_ex_gw_{roic:.2f}_gm_{gm3:.2f}"
    if arche == "bank":
        return False, "bank_excluded_or_routed"
    return False, "archetype_routes_to_review"


QUALITY_TIERS = [
    ("Elite",    {"roic": 0.25, "growth": 0.10}, 28),
    ("High",     {"roic": 0.20, "growth": 0.07}, 22),
    ("Solid",    {"roic": 0.15, "growth": 0.05}, 16),
    ("Average",  {"roic": 0.10, "growth": 0.03}, 12),
    ("Marginal", {"roic": 0.00, "growth": -1.0}, 8),
]


def classify_tier(m: dict) -> tuple[str, float]:
    r_net = m.get("roic_pre_3y") if pd.notna(m.get("roic_pre_3y")) else m.get("roic_pre_tax")
    r_tan = m.get("roic_pre_tangible_3y") if pd.notna(m.get("roic_pre_tangible_3y")) else m.get("roic_pre_tangible")
    if pd.notna(r_net) and pd.notna(r_tan):
        roic = min(r_net, r_tan)
    else:
        roic = r_net if pd.notna(r_net) else r_tan
    g = m.get("revt_cagr_5y")
    if pd.isna(g):
        g = m.get("revt_cagr_3y")
    if pd.isna(roic) or pd.isna(g):
        return "Marginal", 8
    for name, thr, fpe in QUALITY_TIERS:
        if roic >= thr["roic"] and g >= thr["growth"]:
            return name, fpe
    return "Marginal", 8


def _pass(metric, op, threshold) -> bool | None:
    if metric is None or pd.isna(metric):
        return None
    if op == ">=": return metric >= threshold
    if op == "<=": return metric <= threshold
    if op == ">":  return metric > threshold
    if op == "<":  return metric < threshold
    raise ValueError(op)


def derive_flags(row: pd.Series) -> dict:
    """Per-filter pass/fail flags. NaN → treat as pass. passes_quant = all()."""
    depositories, etfs = _hard_excludes()
    arche = row.get("archetype")
    flags = {}
    flags["pass_leverage"] = _pass(row.get("debt_ebitda"), "<=", 5)
    flags["pass_intcov"] = _pass(row.get("intcov"), ">=", 2)

    mc = row.get("maturity_cliff_2y")
    ic = row.get("intcov")
    if pd.notna(mc) and mc > 0.20 and (pd.isna(ic) or ic < 4):
        flags["pass_maturity_cliff"] = False
    else:
        flags["pass_maturity_cliff"] = True

    flags["pass_clean_earnings"] = _pass(row.get("ni_clean_pct"), ">=", 0.5)

    ni_clean = row.get("ni_clean")
    flags["pass_loss_year"] = not (pd.notna(ni_clean) and ni_clean < 0 and arche != "cyclical")

    flags["pass_revenue"] = _pass(row.get("revt_cagr_3y"), ">=", -0.05)

    if arche in ("trad-ops", "cyclical"):
        fcf_ni = row.get("fcf_to_ni_3y")
        capx_s = row.get("capex_to_sales_3y")
        flags["pass_cash_conversion"] = not (
            pd.notna(fcf_ni) and fcf_ni < 0.4
            and pd.notna(capx_s) and capx_s < 0.10
        )
    elif arche == "asset-light":
        flags["pass_cash_conversion"] = _pass(row.get("fcf_to_ni_3y"), ">=", 0.6)
    else:
        flags["pass_cash_conversion"] = True

    if arche == "cyclical":
        roic3 = row.get("roic_pre_3y")
        roic5 = row.get("roic_pre_tax")
        no_franchise = (pd.notna(roic3) and roic3 < 0.08) and (pd.isna(roic5) or roic5 < 0.08)
        flags["pass_franchise"] = not no_franchise
    elif arche == "unclear":
        roic3 = row.get("roic_pre_3y")
        roic3t = row.get("roic_pre_tangible_3y")
        cands = [v for v in (roic3, roic3t) if pd.notna(v)]
        flags["pass_franchise"] = (max(cands) >= 0.10) if cands else True
    else:
        flags["pass_franchise"] = True

    qgp = row.get("quality_gate_passed")
    if pd.isna(qgp):
        flags["pass_quality_gate"] = True
    else:
        flags["pass_quality_gate"] = bool(qgp)

    tkr = (row.get("ticker") or "").upper()
    flags["pass_depository_exclude"] = tkr not in depositories and arche != "bank"
    flags["pass_etf_exclude"] = tkr not in etfs

    for k, v in flags.items():
        if v is None:
            flags[k] = True

    flags["passes_quant"] = all(flags.values())
    return flags


def run_screen(major_purchases: pd.DataFrame,
               cutoff: str,
               live_pe: bool = True,
               cache_dir=None) -> pd.DataFrame:
    """One row per (manager, quarter, ticker) with metrics + passes_quant."""
    depositories, _ = _hard_excludes()
    buys = major_purchases.copy()
    buys = buys[~buys["ticker"].isin(depositories)]
    buys["quarter_end"] = buys["quarter"].apply(
        lambda q: pd.Timestamp(
            year=int(q[:4]),
            month={1: 3, 2: 6, 3: 9, 4: 12}[int(q[-1])],
            day={1: 31, 2: 30, 3: 30, 4: 31}[int(q[-1])],
        )
    )
    buys["cusip8"] = buys["cusip"].astype(str).str[:8]

    cutoff_ts = pd.Timestamp(cutoff)
    cutoff_str = cutoff_ts.strftime("%Y-%m-%d")

    fund = da.load_fund(cutoff=cutoff_str)
    if live_pe:
        unique_tickers = sorted(buys["ticker"].dropna().unique().tolist())
        mkt_cap_lookup = da.fetch_mkt_caps(unique_tickers, cutoff_ts, cache_dir=cache_dir)
        ratios = da.load_ratios_live(cutoff_ts, mkt_cap_lookup)
    else:
        ratios = da.load_ratios(cutoff=cutoff_str)

    cu = fund.dropna(subset=["cusip", "gvkey"]).copy()
    cu["cusip8"] = cu["cusip"].astype(str).str.strip().str.zfill(9).str[:8]
    cu = cu.sort_values("datadate").drop_duplicates("cusip8", keep="last")
    cusip_to_gvkey = dict(zip(cu["cusip8"], cu["gvkey"]))
    ft = fund.dropna(subset=["tic", "gvkey"]).sort_values("datadate") \
             .drop_duplicates("tic", keep="last")
    tic_to_gv = dict(zip(ft["tic"], ft["gvkey"]))

    fund_by_gv = {gv: g for gv, g in fund.groupby("gvkey")}

    rows = []
    for _, b in buys.iterrows():
        gv = cusip_to_gvkey.get(b["cusip8"]) or tic_to_gv.get(b["ticker"])
        out = {
            "quarter": b["quarter"],
            "cik": b["cik"],
            "manager_name": b["manager_name"],
            "action": b["action"],
            "ticker": b["ticker"],
            "cusip": b["cusip"],
            "issuer_name": b.get("issuer_name"),
            "shares_t": b.get("shares_t", b.get("shares")),
            "shares_prev": b.get("shares_prev"),
            "value_thousands_t": b.get("value_thousands_t", b.get("value_thousands")),
            "position_weight": b["position_weight"],
            "incremental_weight": b["incremental_weight"],
            "portfolio_value_thousands": b.get("portfolio_value_thousands"),
            "incremental_value_thousands": b.get("incremental_value_thousands"),
            "quarter_end": b["quarter_end"],
            "gvkey": gv,
        }
        if not gv or gv not in fund_by_gv:
            out["archetype"] = "unclear"
            out["archetype_reason"] = "no_gvkey"
            out["passes_quant"] = False
            rows.append(out)
            continue
        g = fund_by_gv[gv]
        as_of = b["quarter_end"]
        trailing = g[(g["datadate"] <= as_of) & (g["datadate"] >= as_of - pd.Timedelta(days=550))]
        if trailing.empty:
            out["archetype"] = "unclear"
            out["archetype_reason"] = "no_recent_fund"
            out["passes_quant"] = False
            rows.append(out)
            continue

        m = per_gvkey_metrics(g, as_of)
        out.update({k: v for k, v in m.items() if not k.startswith("_")})

        arche, arche_reason = tag_archetype({**m, "ticker": b["ticker"]})
        out["archetype"] = arche
        out["archetype_reason"] = arche_reason

        # GATED_ARCHETYPES have a defined quality gate; reit / utility /
        # holdco / bank leave NaN so derive_flags treats them as pass-through.
        # (Utilities are excluded from the MF universe anyway, so they can
        # never be selected regardless.)
        if arche in GATED_ARCHETYPES:
            passed, qreason = quality_gate(arche, m)
            out["quality_gate_passed"] = passed
            out["quality_gate_reason"] = qreason
        else:
            out["quality_gate_passed"] = None
            out["quality_gate_reason"] = f"archetype_{arche}_no_gate"
        tier, fair_pe = classify_tier(m)
        out["quality_tier"] = tier
        out["fair_pe"] = fair_pe

        flags = derive_flags(pd.Series(out))
        out.update(flags)
        rows.append(out)

    return pd.DataFrame(rows)
