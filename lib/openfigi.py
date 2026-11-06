"""CUSIP -> ticker via the OpenFIGI mapping API, with a local parquet cache.

OpenFIGI knows only *current* identifiers. Retired CUSIPs (pre-split share
classes, delisted or merged issuers) come back empty; those are cached as
misses and left for the caller's fallback. Hits are re-queried after
`openfigi.hit_ttl_days` (tickers change on renames), misses after
`openfigi.miss_ttl_days`.

CUSIPs whose first character is a letter are CINS codes (non-US issuers,
e.g. Transocean H8817H100) and must be sent as ID_CINS, not ID_CUSIP.

Delisted lines come back with Bloomberg placeholder tickers (digits plus a
letter, e.g. Golden Ocean -> 2663476D). Those are treated as misses so the
caller's fallback supplies the last traded ticker.

Tickers are normalised to the Compustat dot form (BRK/B -> BRK.B) so the rest
of the pipeline, which converts '.' -> '-' for yfinance, is unchanged.

Rate limits: without a key 25 requests/min, 10 CUSIPs per request. An optional
key at `api_keys.openfigi` in the secrets YAML raises this to 25 requests per
6 s, 100 CUSIPs per request.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import pandas as pd
import yaml

from . import config

URL = "https://api.openfigi.com/v3/mapping"
SECRETS = Path(r"C:\key-variables\key-variables.yaml")
DELISTED = re.compile(r"^\d+[A-Z]?$")
COLS = ["cusip", "ticker", "exch_code", "security_type", "name", "fetched_at"]


def _api_key() -> str | None:
    try:
        keys = yaml.safe_load(SECRETS.read_text(encoding="utf-8")).get("api_keys", {})
        return keys.get("openfigi") or None
    except (OSError, yaml.YAMLError, AttributeError):
        return None


def _norm_cusip(c) -> str:
    return str(c).strip().upper().zfill(9)


def _job(cusip: str) -> dict:
    id_type = "ID_CINS" if cusip[0].isalpha() else "ID_CUSIP"
    return {"idType": id_type, "idValue": cusip, "exchCode": "US"}


def _post(jobs: list[dict], key: str | None) -> list[dict]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    req = urllib.request.Request(URL, data=json.dumps(jobs).encode(), headers=headers)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("ratelimit-reset", 10)) + 1)
                continue
            raise
        except urllib.error.URLError:
            time.sleep(2 ** attempt)
    raise RuntimeError("OpenFIGI: retries exhausted")


def _load_cache(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=COLS)


def fetch(cusips: list[str], *, key: str | None) -> pd.DataFrame:
    """Query OpenFIGI for `cusips`; return one row per CUSIP (ticker None on a miss)."""
    batch, pause = (100, 0.25) if key else (10, 2.5)
    now = pd.Timestamp.now(tz="UTC")
    out: list[dict] = []
    for i in range(0, len(cusips), batch):
        chunk = cusips[i:i + batch]
        res = _post([_job(c) for c in chunk], key)
        for c, r in zip(chunk, res):
            d = r.get("data") or []
            hit = d[0] if d else {}
            t = hit.get("ticker")
            out.append({
                "cusip": c,
                "ticker": t.replace("/", ".") if t else None,
                "exch_code": hit.get("exchCode"),
                "security_type": hit.get("securityType"),
                "name": hit.get("name"),
                "fetched_at": now,
            })
        print(f"\r[openfigi] {min(i + batch, len(cusips))}/{len(cusips)}", end="", flush=True)
        time.sleep(pause)
    if cusips:
        print()
    return pd.DataFrame(out, columns=COLS)


def cusip_to_ticker(cusips, *, offline: bool = False) -> dict[str, str]:
    """{9-char CUSIP: ticker} for every CUSIP OpenFIGI can map.

    Unknown or stale-miss CUSIPs are fetched and written to the cache, unless
    `offline`, in which case only cached results are used.
    """
    cfg = config.load()["openfigi"]
    path = config.path("openfigi_cache")
    want = sorted({_norm_cusip(c) for c in cusips if pd.notna(c)})
    cache = _load_cache(path)

    if not offline:
        now = pd.Timestamp.now(tz="UTC")
        age = now - pd.to_datetime(cache["fetched_at"], utc=True)
        ttl = pd.to_timedelta(cache["ticker"].notna().map(
            {True: cfg["hit_ttl_days"], False: cfg["miss_ttl_days"]}), unit="D")
        fresh = cache[age < ttl]
        todo = sorted(set(want) - set(fresh["cusip"]))
        if todo:
            try:
                new = fetch(todo, key=_api_key())
            except (urllib.error.URLError, RuntimeError) as e:
                print(f"\n[openfigi] fetch failed ({e}); using cache only")
                new = None
            if new is not None:
                cache = pd.concat([cache[~cache["cusip"].isin(todo)], new], ignore_index=True)
                path.parent.mkdir(parents=True, exist_ok=True)
                cache.to_parquet(path, index=False)

    hits = cache[cache["cusip"].isin(want) & cache["ticker"].notna()]
    hits = hits[~hits["ticker"].str.match(DELISTED)]
    return dict(zip(hits["cusip"], hits["ticker"]))
