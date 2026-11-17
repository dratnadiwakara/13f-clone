"""Fetch individual 13F-HR filings from EDGAR into a provisional sidecar parquet.

Why this exists
---------------
SEC's *bulk* 13F datasets lag the 45-day filing deadline by roughly a quarter --
the ZIP covering 2026Q2 does not publish until ~Oct/Nov 2026. But the individual
13F-HR filings are public on EDGAR the day they are filed. For a 50-manager
candidate universe that is a 2-3 month information lead.

This script fetches those filings directly and writes a **provisional sidecar**:

    materials/13f/provisional/13f_provisional_{QUARTER}.parquet
    materials/13f/provisional/13f_provisional_{QUARTER}.manifest.json

HARD RULE -- the sidecar is NEVER merged into 13f_holdings.parquet.
Appending it would permanently advance that file's max-quarter floor, and the
append path only ever takes quarters strictly greater than the floor. The
authoritative quarter arriving two months later would then be skipped forever.
The sidecar is a separate file, consumed opt-in, and deleted once the real
quarter lands. See `reconcile_provisional.py` for the changeover.

Schema matches 13f_holdings.parquet exactly (same 11 columns, same arrow types)
so downstream loaders can concatenate without casting.

Usage
-----
    python materials/13f/fetch_13f_filings.py --quarter 2026Q2
    python materials/13f/fetch_13f_filings.py --quarter 2026Q2 --dry-run
    python materials/13f/fetch_13f_filings.py --quarter 2026Q2 --require-all
    python materials/13f/fetch_13f_filings.py --quarter 2026Q2 --refresh

Exit codes
----------
    0  sidecar written (or dry-run completed)
    1  bad arguments
    2  a filing failed to download or parse
    3  coverage gate failed (--require-all and some manager has not filed)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVISIONAL_DIR = REPO_ROOT / "data" / "13f" / "provisional"
DEFAULT_CACHE_DIR = PROVISIONAL_DIR / "_cache"
DEFAULT_MANAGERS = REPO_ROOT / "data" / "managers" / "candidate_managers.txt"
DEFAULT_HOLDINGS = REPO_ROOT / "data" / "13f" / "13f_holdings_slim.parquet"

# SEC fair access needs a contact address in the User-Agent. Set it in the
# SEC_USER_AGENT environment variable, e.g. "investments-research/1.0 you@example.com".
USER_AGENT = os.environ.get("SEC_USER_AGENT", "")
REQUEST_SPACING_S = 0.12          # <= 10 req/s per SEC fair access
SUBMISSIONS_TTL_S = 6 * 3600
MAX_RETRIES = 4

EXIT_OK, EXIT_BAD_ARGS, EXIT_FETCH_FAILED, EXIT_COVERAGE_FAILED = 0, 1, 2, 3

# Exact schema of materials/13f/13f_holdings.parquet.
TARGET_SCHEMA = pa.schema([
    ("quarter", pa.large_string()),
    ("cik", pa.large_string()),
    ("manager_name", pa.large_string()),
    ("amendment_flag", pa.large_string()),
    ("issuer_name", pa.large_string()),
    ("cusip", pa.large_string()),
    ("value_thousands", pa.int64()),
    ("shares_or_prn_amount", pa.float64()),
    ("shares_or_prn_type", pa.large_string()),
    ("put_call", pa.large_string()),
    ("investment_discretion", pa.large_string()),
])

_CIK_RE = re.compile(r"^\s*(?:[A-Za-z0-9]+\s+)?(\d{10})\b")
_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")

# Plausible share-price band used to infer whether `value` is dollars or thousands.
PRICE_LO, PRICE_HI = 0.5, 10_000.0


# --------------------------------------------------------------------------
# quarter helpers
# --------------------------------------------------------------------------

def quarter_end_date(quarter: str) -> date:
    m = _QUARTER_RE.match(quarter)
    if not m:
        raise ValueError(f"bad quarter {quarter!r}, expected YYYYQn")
    year, qn = int(m.group(1)), int(m.group(2))
    return date(year, *{1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[qn])


def filing_deadline(quarter: str) -> date:
    return quarter_end_date(quarter) + pd.Timedelta(days=45).to_pytimedelta()


def previous_quarter(quarter: str) -> str:
    m = _QUARTER_RE.match(quarter)
    if not m:
        raise ValueError(f"bad quarter {quarter!r}")
    year, qn = int(m.group(1)), int(m.group(2))
    return f"{year - 1}Q4" if qn == 1 else f"{year}Q{qn - 1}"


def prior_quarter_filers(holdings_parquet: Path, prior_q: str,
                         candidates: list[str]) -> set[str] | None:
    """CIKs from `candidates` that filed in `prior_q`, per the authoritative parquet.

    This is the correct denominator for a coverage gate. The candidate list
    carries managers who wound down years ago -- demanding a filing from them
    would mean the gate never passes. Returns None if the baseline is
    unavailable, in which case callers fall back to the full candidate list.
    """
    if not holdings_parquet.exists():
        return None
    try:
        handle = pq.ParquetFile(holdings_parquet)
        try:
            wanted = set(candidates)
            found: set[str] = set()
            for batch in handle.iter_batches(batch_size=1_048_576,
                                             columns=["quarter", "cik"]):
                df = batch.to_pandas()
                hit = df.loc[df["quarter"] == prior_q, "cik"]
                found.update(set(hit.unique()) & wanted)
            return found
        finally:
            handle.close()
    except Exception:  # noqa: BLE001 - baseline is advisory, never fatal
        return None


# --------------------------------------------------------------------------
# manager universe
# --------------------------------------------------------------------------

def load_candidate_ciks(path: Path) -> list[str]:
    """Parse candidate_managers.txt -> ordered unique CIK10 list."""
    out: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("##"):
            continue
        m = _CIK_RE.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

_last_request_at = 0.0


def _http_get(url: str, *, binary: bool = False):
    """GET with SEC-compliant spacing and retry/backoff."""
    global _last_request_at
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        gap = time.monotonic() - _last_request_at
        if gap < REQUEST_SPACING_S:
            time.sleep(REQUEST_SPACING_S - gap)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
            _last_request_at = time.monotonic()
            return raw if binary else raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            _last_request_at = time.monotonic()
            if e.code == 404:
                raise
            last_err = e
        except Exception as e:  # noqa: BLE001 - network layer, retry everything else
            _last_request_at = time.monotonic()
            last_err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {MAX_RETRIES} attempts: {url} ({last_err})")


def _cached_get(url: str, cache_path: Path, *, ttl_s: float | None, refresh: bool) -> str:
    """Disk-cached GET. ttl_s=None means cache forever (filings are immutable)."""
    if not refresh and cache_path.exists():
        if ttl_s is None:
            return cache_path.read_text(encoding="utf-8")
        age = time.time() - cache_path.stat().st_mtime
        if age < ttl_s:
            return cache_path.read_text(encoding="utf-8")
    text = _http_get(url)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(text, encoding="utf-8")
    return text


# --------------------------------------------------------------------------
# EDGAR discovery
# --------------------------------------------------------------------------

@dataclass
class FilingRef:
    cik: str
    form: str                # 13F-HR or 13F-HR/A
    accession: str
    filing_date: str
    report_date: str

    @property
    def acc_nodash(self) -> str:
        return self.accession.replace("-", "")

    @property
    def dir_url(self) -> str:
        return (f"https://www.sec.gov/Archives/edgar/data/"
                f"{int(self.cik)}/{self.acc_nodash}/")


def find_period_filings(cik: str, period_end: date, cache_dir: Path,
                        refresh: bool) -> list[FilingRef]:
    """All 13F-HR / 13F-HR/A filings whose reportDate == period_end.

    Walks `recent` plus any older submission shards, so a manager who files a
    late amendment months after the fact is still found.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    text = _cached_get(url, cache_dir / "submissions" / f"CIK{cik}.json",
                       ttl_s=SUBMISSIONS_TTL_S, refresh=refresh)
    doc = json.loads(text)
    target = period_end.isoformat()
    refs: list[FilingRef] = []

    def _scan(block: dict) -> None:
        forms = block.get("form", [])
        for i, form in enumerate(forms):
            if not form.startswith("13F-HR"):
                continue
            if block["reportDate"][i] != target:
                continue
            refs.append(FilingRef(
                cik=cik, form=form,
                accession=block["accessionNumber"][i],
                filing_date=block["filingDate"][i],
                report_date=block["reportDate"][i],
            ))

    _scan(doc["filings"]["recent"])
    for shard in doc["filings"].get("files", []):
        shard_url = f"https://data.sec.gov/submissions/{shard['name']}"
        shard_text = _cached_get(shard_url, cache_dir / "submissions" / shard["name"],
                                 ttl_s=SUBMISSIONS_TTL_S, refresh=refresh)
        _scan(json.loads(shard_text))

    refs.sort(key=lambda r: (r.filing_date, r.accession))
    return refs


def download_filing_xml(ref: FilingRef, cache_dir: Path,
                        refresh: bool) -> tuple[str, str]:
    """Return (primary_doc_xml, information_table_xml).

    The info-table filename is not standardised across filers, so the directory
    listing is scanned for the XML that is not primary_doc.xml.
    """
    dest = cache_dir / "filings" / ref.cik / ref.acc_nodash
    idx_text = _cached_get(ref.dir_url + "index.json", dest / "index.json",
                           ttl_s=None, refresh=refresh)
    items = json.loads(idx_text)["directory"]["item"]
    xml_names = [it["name"] for it in items if it["name"].lower().endswith(".xml")]

    primary_name = next(
        (n for n in xml_names if n.lower().endswith("primary_doc.xml")), None)
    if primary_name is None:
        raise RuntimeError(f"no primary_doc.xml in {ref.dir_url}")
    primary = _cached_get(ref.dir_url + primary_name, dest / "primary_doc.xml",
                          ttl_s=None, refresh=refresh)

    info_xml = ""
    for name in xml_names:
        if name == primary_name:
            continue
        candidate = _cached_get(ref.dir_url + name, dest / name,
                                ttl_s=None, refresh=refresh)
        if "informationTable" in candidate or "<infoTable" in candidate:
            info_xml = candidate
            break
    if not info_xml:
        raise RuntimeError(f"no information table XML in {ref.dir_url}")
    return primary, info_xml


# --------------------------------------------------------------------------
# XML parsing
# --------------------------------------------------------------------------

def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_text(elem: ET.Element, name: str) -> str:
    for child in elem.iter():
        if _localname(child.tag) == name and child.text:
            return child.text.strip()
    return ""


@dataclass
class CoverPage:
    manager_name: str
    is_amendment: bool
    amendment_type: str          # RESTATEMENT | NEW HOLDINGS | ""
    amendment_no: str


def parse_primary_doc(xml_text: str) -> CoverPage:
    root = ET.fromstring(xml_text)
    manager = ""
    for elem in root.iter():
        if _localname(elem.tag) == "filingManager":
            manager = _find_text(elem, "name")
            break
    return CoverPage(
        manager_name=manager,
        is_amendment=_find_text(root, "isAmendment").lower() == "true",
        amendment_type=_find_text(root, "amendmentType").strip().upper(),
        amendment_no=_find_text(root, "amendmentNo"),
    )


def parse_infotable(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows: list[dict] = []
    for elem in root.iter():
        if _localname(elem.tag) != "infoTable":
            continue
        fields: dict[str, str] = {}
        for child in elem.iter():
            ln = _localname(child.tag)
            if ln in ("nameOfIssuer", "cusip", "value", "sshPrnamt",
                      "sshPrnamtType", "investmentDiscretion", "putCall"):
                if child.text and ln not in fields:
                    fields[ln] = child.text.strip()
        if "cusip" not in fields:
            continue
        try:
            value_raw = int(float(fields.get("value", "0") or 0))
            shares = float(fields.get("sshPrnamt", "0") or 0)
        except ValueError:
            continue
        put_call = fields.get("putCall", "").strip().title()
        rows.append({
            "issuer_name": fields.get("nameOfIssuer", "").strip(),
            # NOT upper-cased. The SEC bulk feed preserves the filer's original
            # case (Akre files `48251w104`), and downstream joins are on the raw
            # cusip string. Normalising here would make a continuing position
            # look like a new buy when a sidecar quarter joins a bulk quarter.
            "cusip": fields["cusip"].strip(),
            "value_raw": value_raw,
            "shares_or_prn_amount": shares,
            "shares_or_prn_type": fields.get("sshPrnamtType", "SH").strip().upper(),
            "put_call": put_call if put_call in ("Put", "Call") else "",
            "investment_discretion": fields.get("investmentDiscretion", "").strip().upper(),
        })
    return rows


# --------------------------------------------------------------------------
# amendment resolution + unit inference
# --------------------------------------------------------------------------

def resolve_filings(parsed: list[tuple[FilingRef, CoverPage, list[dict]]]
                    ) -> tuple[list[dict], str, str]:
    """Apply SEC amendment semantics.

    RESTATEMENT replaces the entire holdings report -- the latest one wins
    outright. NEW HOLDINGS is additive on top of whatever preceded it. Returns
    (rows, amendment_flag, note).
    """
    if not parsed:
        return [], "N", "no filings"

    restatements = [p for p in parsed
                    if p[1].is_amendment and p[1].amendment_type == "RESTATEMENT"]
    if restatements:
        ref, _cover, rows = restatements[-1]
        additive = [p for p in parsed
                    if p[1].is_amendment
                    and p[1].amendment_type != "RESTATEMENT"
                    and p[0].filing_date > ref.filing_date]
        rows = list(rows)
        for _r, _c, extra in additive:
            rows.extend(extra)
        note = f"restatement {ref.accession}"
        if additive:
            note += f" + {len(additive)} additive"
        return rows, "Y", note

    originals = [p for p in parsed if not p[1].is_amendment]
    additive = [p for p in parsed if p[1].is_amendment]
    rows: list[dict] = []
    if originals:
        rows.extend(originals[-1][2])
    for _r, _c, extra in additive:
        rows.extend(extra)
    flag = "Y" if additive else "N"
    note = "original" if not additive else f"original + {len(additive)} additive"
    return rows, flag, note


def infer_value_scale(rows: list[dict]) -> tuple[int, str]:
    """Decide whether this filer reports `value` in dollars or thousands.

    SEC moved Form 13F from thousands to whole dollars effective 2023-01-03, but
    compliance is not universal -- ~4% of filers still report thousands as of
    2026Q1. Units are consistent *within* a filer, so the decision is made once
    per filing off the median implied share price.
    """
    prices = [r["value_raw"] / r["shares_or_prn_amount"]
              for r in rows
              if r["shares_or_prn_type"] == "SH"
              and r["shares_or_prn_amount"] > 0
              and r["value_raw"] > 0
              and not r["put_call"]]
    if not prices:
        return 1, "no_priceable_rows_assumed_dollars"
    med = float(pd.Series(prices).median())
    raw_ok = PRICE_LO <= med <= PRICE_HI
    k_ok = PRICE_LO <= med * 1000 <= PRICE_HI
    if raw_ok and not k_ok:
        return 1, "raw_dollars"
    if k_ok and not raw_ok:
        return 1000, "thousands"
    if raw_ok and k_ok:
        return 1, "raw_dollars_ambiguous"
    return 1, "out_of_band_assumed_dollars"


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

@dataclass
class ManagerResult:
    cik: str
    manager_name: str = ""
    status: str = "missing"          # filed | missing | failed
    form: str = ""
    accession: str = ""
    filing_date: str = ""
    n_positions: int = 0
    unit_note: str = ""
    value_scale: int = 1
    total_value_usd: int = 0
    amendment_flag: str = "N"
    note: str = ""
    error: str = ""
    rows: list[dict] = field(default_factory=list, repr=False)


def fetch_manager(cik: str, quarter: str, period_end: date, cache_dir: Path,
                  refresh: bool) -> ManagerResult:
    res = ManagerResult(cik=cik)
    try:
        refs = find_period_filings(cik, period_end, cache_dir, refresh)
    except Exception as e:  # noqa: BLE001
        res.status, res.error = "failed", f"submissions: {e}"
        return res
    if not refs:
        return res  # status stays "missing"

    parsed: list[tuple[FilingRef, CoverPage, list[dict]]] = []
    for ref in refs:
        try:
            primary, info = download_filing_xml(ref, cache_dir, refresh)
            cover = parse_primary_doc(primary)
            rows = parse_infotable(info)
        except Exception as e:  # noqa: BLE001
            res.status, res.error = "failed", f"{ref.accession}: {e}"
            return res
        parsed.append((ref, cover, rows))

    rows, amend_flag, note = resolve_filings(parsed)
    scale, unit_note = infer_value_scale(rows)
    last_ref, last_cover, _ = parsed[-1]

    for r in rows:
        r["value_thousands"] = int(r.pop("value_raw") * scale)

    res.manager_name = last_cover.manager_name or ""
    res.status = "filed"
    res.form = last_ref.form
    res.accession = last_ref.accession
    res.filing_date = last_ref.filing_date
    res.n_positions = len(rows)
    res.unit_note = unit_note
    res.value_scale = scale
    res.total_value_usd = int(sum(r["value_thousands"] for r in rows))
    res.amendment_flag = amend_flag
    res.note = note
    res.rows = rows
    return res


def results_to_table(results: list[ManagerResult], quarter: str) -> pa.Table:
    records: list[dict] = []
    for res in results:
        if res.status != "filed":
            continue
        for r in res.rows:
            records.append({
                "quarter": quarter,
                "cik": res.cik,
                "manager_name": res.manager_name,
                "amendment_flag": res.amendment_flag,
                "issuer_name": r["issuer_name"],
                "cusip": r["cusip"],
                "value_thousands": r["value_thousands"],
                "shares_or_prn_amount": float(r["shares_or_prn_amount"]),
                "shares_or_prn_type": r["shares_or_prn_type"],
                "put_call": r["put_call"],
                "investment_discretion": r["investment_discretion"],
            })
    if not records:
        return TARGET_SCHEMA.empty_table()
    df = pd.DataFrame.from_records(records)
    return pa.Table.from_pandas(df, schema=TARGET_SCHEMA, preserve_index=False)


def write_manifest(results: list[ManagerResult], quarter: str, path: Path,
                   requested: list[str], total_rows: int,
                   expected: set[str] | None) -> dict:
    filed = [r for r in results if r.status == "filed"]
    missing = [r for r in results if r.status == "missing"]
    failed = [r for r in results if r.status == "failed"]
    # Only managers who filed the prior quarter are expected to file this one.
    missing_expected = [r.cik for r in missing
                        if expected is None or r.cik in expected]
    missing_inactive = [r.cik for r in missing if r.cik not in missing_expected]
    manifest = {
        "quarter": quarter,
        "source": "EDGAR 13F-HR individual filings (PROVISIONAL)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_end": quarter_end_date(quarter).isoformat(),
        "filing_deadline": filing_deadline(quarter).isoformat(),
        "value_units": "raw US dollars (per-filer thousands->dollars normalised)",
        "n_requested": len(requested),
        "n_expected": len(expected) if expected is not None else None,
        "expected_basis": (f"filed {previous_quarter(quarter)} per authoritative parquet"
                           if expected is not None else "full candidate list (no baseline)"),
        "n_filed": len(filed),
        "n_missing": len(missing),
        "n_failed": len(failed),
        "total_rows": total_rows,
        # "complete" means every manager who filed last quarter has filed this
        # one. Managers who wound down years ago do not block it.
        "complete": not missing_expected and not failed,
        "missing_expected_ciks": missing_expected,
        "missing_inactive_ciks": missing_inactive,
        "failed_ciks": {r.cik: r.error for r in failed},
        "managers": [
            {
                "cik": r.cik, "manager_name": r.manager_name, "status": r.status,
                "expected": expected is None or r.cik in expected,
                "form": r.form, "accession": r.accession,
                "filing_date": r.filing_date, "n_positions": r.n_positions,
                "unit_note": r.unit_note, "value_scale": r.value_scale,
                "total_value_usd": r.total_value_usd,
                "amendment_flag": r.amendment_flag, "note": r.note,
                "error": r.error,
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quarter", required=True, help="YYYYQn, e.g. 2026Q2")
    ap.add_argument("--managers-file", type=Path, default=DEFAULT_MANAGERS)
    ap.add_argument("--out-dir", type=Path, default=PROVISIONAL_DIR)
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ap.add_argument("--holdings-parquet", type=Path, default=DEFAULT_HOLDINGS,
                    help="Authoritative parquet, used to derive who is expected to file.")
    ap.add_argument("--cik", action="append", default=None,
                    help="Fetch only this CIK (repeatable). Overrides --managers-file.")
    ap.add_argument("--require-all", action="store_true",
                    help="Exit 3 unless every EXPECTED manager (one that filed the "
                         "prior quarter) has filed.")
    ap.add_argument("--refresh", action="store_true",
                    help="Bypass caches (picks up newly filed amendments).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report who has filed. No parquet written.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not _QUARTER_RE.match(args.quarter):
        print(f"[error] bad --quarter {args.quarter!r}, expected YYYYQn", file=sys.stderr)
        return EXIT_BAD_ARGS
    if not USER_AGENT:
        print("[error] SEC_USER_AGENT is not set; SEC requires a contact address "
              "in the User-Agent", file=sys.stderr)
        return EXIT_BAD_ARGS

    period_end = quarter_end_date(args.quarter)
    deadline = filing_deadline(args.quarter)
    today = date.today()

    if args.cik:
        ciks = [c.zfill(10) for c in args.cik]
    else:
        if not args.managers_file.exists():
            print(f"[error] managers file not found: {args.managers_file}", file=sys.stderr)
            return EXIT_BAD_ARGS
        ciks = load_candidate_ciks(args.managers_file)
    if not ciks:
        print("[error] no CIKs resolved", file=sys.stderr)
        return EXIT_BAD_ARGS

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    log(f"[quarter] {args.quarter}  period_end={period_end}  deadline={deadline}")
    if today < deadline:
        log(f"[warn] filing deadline has not passed ({deadline}); coverage will be partial")
    log(f"[universe] {len(ciks)} candidate managers from "
        f"{'--cik' if args.cik else args.managers_file.name}")

    prior_q = previous_quarter(args.quarter)
    expected = prior_quarter_filers(args.holdings_parquet, prior_q, ciks)
    if expected is None:
        log(f"[baseline] {args.holdings_parquet.name} unavailable; "
            f"treating all {len(ciks)} candidates as expected")
    else:
        log(f"[baseline] {len(expected)}/{len(ciks)} candidates filed {prior_q} "
            f"-> expected to file {args.quarter}")

    results: list[ManagerResult] = []
    for i, cik in enumerate(ciks, 1):
        res = fetch_manager(cik, args.quarter, period_end, args.cache_dir, args.refresh)
        results.append(res)
        if res.status == "filed":
            log(f"  [{i:>3}/{len(ciks)}] {cik}  {res.manager_name[:38]:40s} "
                f"{res.n_positions:>5} pos  {res.form:<9} {res.filing_date}  {res.unit_note}")
        elif res.status == "missing":
            log(f"  [{i:>3}/{len(ciks)}] {cik}  {'-- not filed --':40s}")
        else:
            log(f"  [{i:>3}/{len(ciks)}] {cik}  FAILED: {res.error}")

    filed = [r for r in results if r.status == "filed"]
    missing = [r for r in results if r.status == "missing"]
    failed = [r for r in results if r.status == "failed"]
    total_rows = sum(r.n_positions for r in filed)
    missing_expected = [r for r in missing
                        if expected is None or r.cik in expected]
    missing_inactive = [r for r in missing if r not in missing_expected]

    log("")
    denom = len(expected) if expected is not None else len(ciks)
    filed_expected = [r for r in filed if expected is None or r.cik in expected]
    new_filers = [r for r in filed if expected is not None and r.cik not in expected]
    log(f"[coverage] filed {len(filed)}/{len(ciks)} candidates  "
        f"({len(filed_expected)}/{denom} expected"
        + (f", +{len(new_filers)} new filer(s)" if new_filers else "")
        + f")  failed {len(failed)}  rows {total_rows:,}")
    if missing_expected:
        log(f"[late]     {len(missing_expected)} expected filer(s) have NOT filed: "
            f"{', '.join(r.cik for r in missing_expected)}")
    if missing_inactive:
        log(f"[inactive] {len(missing_inactive)} candidate(s) did not file "
            f"{prior_q} either; not counted against coverage")

    if failed:
        log(f"[error] {len(failed)} manager(s) failed to fetch; no sidecar written")
        return EXIT_FETCH_FAILED

    if missing_expected and args.require_all:
        log(f"[error] --require-all set and {len(missing_expected)} expected "
            f"manager(s) have not filed")
        return EXIT_COVERAGE_FAILED

    if args.dry_run:
        log("[dry-run] no files written")
        return EXIT_OK

    table = results_to_table(results, args.quarter)
    out_parquet = args.out_dir / f"13f_provisional_{args.quarter}.parquet"
    out_manifest = args.out_dir / f"13f_provisional_{args.quarter}.manifest.json"
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_parquet, compression="snappy", version="2.6")
    manifest = write_manifest(results, args.quarter, out_manifest, ciks,
                              total_rows, expected)

    log(f"[ok] {out_parquet}  ({table.num_rows:,} rows, "
        f"{out_parquet.stat().st_size / 1024:.0f} KB)")
    log(f"[ok] {out_manifest}  (complete={manifest['complete']})")
    log("[note] PROVISIONAL sidecar. Never merge into 13f_holdings.parquet.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
