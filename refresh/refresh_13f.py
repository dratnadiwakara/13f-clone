"""Append newly published SEC bulk 13F quarters to the slim holdings parquet.

Downloads SEC "Form 13F data sets" ZIPs for quarters strictly newer than the
parquet's max quarter, filters to the tracked-manager CIKs, and appends.
Append-only: a run with nothing new makes ZERO writes. Provisional sidecars
are NEVER merged here — they live in data/13f/provisional and are dropped
automatically by lib/holdings once the bulk quarter lands.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from lib import managers  # noqa: E402

PARQUET = REPO / "data/13f/13f_holdings_slim.parquet"
STATE = REPO / "data/13f/13f_holdings_slim.state.json"
INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
# SEC requires a contact address in the User-Agent; read from SEC_USER_AGENT.
UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "")}

COLS = ["quarter", "cik", "manager_name", "amendment_flag", "issuer_name",
        "cusip", "value_thousands", "shares_or_prn_amount", "shares_or_prn_type",
        "put_call", "investment_discretion"]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def quarter_of_link(href: str) -> str | None:
    """Infer YYYYQN from a dataset ZIP name like 01jan2026-31mar2026_form13f.zip
    or 2026q1_form13f.zip."""
    name = href.lower()
    m = re.search(r"(20\d\d)q([1-4])", name)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    m = re.search(r"\d{2}([a-z]{3})(20\d\d)_form13f", name)
    if m and m.group(1) in MONTHS:
        return f"{m.group(2)}Q{(MONTHS[m.group(1)] + 2) // 3}"
    return None


def read_tsv(zf: zipfile.ZipFile, member: str) -> pd.DataFrame:
    path = next(n for n in zf.namelist() if n.upper().endswith(member))
    return pd.read_csv(zf.open(path), sep="\t", dtype=str, low_memory=False)


def parse_zip(content: bytes, ciks: set[str]) -> pd.DataFrame:
    zf = zipfile.ZipFile(io.BytesIO(content))
    sub = read_tsv(zf, "SUBMISSION.TSV").rename(columns={
        "ACCESSION_NUMBER": "accession_no", "CIK": "cik",
        "PERIODOFREPORT": "report_period"})
    sub = sub[sub["cik"].str.zfill(10).isin(ciks)]
    if sub.empty:
        return pd.DataFrame(columns=COLS)
    cov = read_tsv(zf, "COVERPAGE.TSV").rename(columns={
        "ACCESSION_NUMBER": "accession_no", "ISAMENDMENT": "amendment_flag",
        "FILINGMANAGER_NAME": "manager_name"})
    info = read_tsv(zf, "INFOTABLE.TSV").rename(columns={
        "ACCESSION_NUMBER": "accession_no", "NAMEOFISSUER": "issuer_name",
        "CUSIP": "cusip", "VALUE": "value_thousands",
        "SSHPRNAMT": "shares_or_prn_amount", "SSHPRNAMTTYPE": "shares_or_prn_type",
        "PUTCALL": "put_call", "INVESTMENTDISCRETION": "investment_discretion"})
    df = (info.merge(sub[["accession_no", "cik", "report_period"]], on="accession_no")
              .merge(cov[["accession_no", "amendment_flag", "manager_name"]],
                     on="accession_no", how="left"))
    period = pd.to_datetime(df["report_period"], errors="coerce", format="mixed")
    df["quarter"] = period.dt.year.astype("Int64").astype(str) + "Q" + \
        ((period.dt.month + 2) // 3).astype("Int64").astype(str)
    df["value_thousands"] = pd.to_numeric(df["value_thousands"], errors="coerce") \
        .round().astype("Int64")
    df["shares_or_prn_amount"] = pd.to_numeric(df["shares_or_prn_amount"], errors="coerce")
    for c in ("put_call", "investment_discretion", "amendment_flag"):
        df[c] = df[c].fillna("")
    return df[COLS]


def main() -> None:
    state = json.loads(STATE.read_text())
    floor = state["max_quarter"]
    ciks = set(managers.load_tier_map().keys())

    page = requests.get(INDEX_URL, headers=UA, timeout=60).text
    links = sorted({re.sub(r"^/", "https://www.sec.gov/", h) if h.startswith("/") else h
                    for h in re.findall(r'href="([^"]+form13f[^"]*\.zip)"', page, re.I)})
    # ZIP names are FILING-date windows; a Mar-May window holds Q1 REPORTS.
    # Download any window that could contain reports newer than the floor,
    # then filter by the report_period-derived quarter inside.
    todo = [(quarter_of_link(h), h) for h in links]
    todo = sorted((q, h) for q, h in todo if q and q >= floor)
    if not todo:
        print(f"[refresh_13f] nothing newer than {floor} on SEC — no writes")
        return

    frames = []
    for q, href in todo:
        print(f"[refresh_13f] downloading window {q}: {href}")
        r = requests.get(href, headers=UA, timeout=600)
        r.raise_for_status()
        df = parse_zip(r.content, ciks)
        df = df[df["quarter"] > floor]
        print(f"    {len(df):,} tracked-manager rows newer than {floor}")
        frames.append(df)

    new = pd.concat(frames, ignore_index=True)
    if new.empty:
        print("[refresh_13f] no tracked-manager rows in new quarters — no writes")
        return

    base = pd.read_parquet(PARQUET)
    backup = PARQUET.with_suffix(".bak.parquet")
    base.to_parquet(backup, index=False)
    out = pd.concat([base, new], ignore_index=True).sort_values(
        ["quarter", "cik", "cusip"], kind="stable")
    out.to_parquet(PARQUET, index=False)

    qc = out.groupby("quarter").size()
    state.update(rows=int(len(out)), max_quarter=qc.index.max(),
                 quarters={q: int(n) for q, n in qc.items()},
                 written_at=datetime.now(timezone.utc).isoformat())
    STATE.write_text(json.dumps(state, indent=1))
    print(f"[refresh_13f] appended {len(new):,} rows "
          f"({', '.join(q for q, _ in todo)}); backup at {backup.name}")


if __name__ == "__main__":
    main()
