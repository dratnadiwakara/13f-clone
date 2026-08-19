"""Parse candidate_managers.txt. Section 1 = Elite. Section 2 = BacktestElite.
Section 3 = PersistenceSelected. All three sections loaded by default —
opt out via `include_persistence=False`.
"""
from __future__ import annotations
from pathlib import Path
import re

from . import config

EXISTING_MARKER = "## Existing tracked investors"
ELITE_MARKER = "## Elite 13F managers"
PERSISTENCE_MARKER = "## Persistence-selected managers"

_CIK_RE = re.compile(r"^\s*(?:[A-Za-z]+\s+)?(\d{10})\b")


def _path() -> Path:
    return config.path("candidate_managers")


def load_tier_map(include_persistence: bool = True) -> dict[str, str]:
    """{cik10: tier}. tier ∈ {Elite, BacktestElite, PersistenceSelected}."""
    tier_map: dict[str, str] = {}
    current: str | None = None
    for line in _path().read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(EXISTING_MARKER):
            current = "Elite"
            continue
        if s.startswith(ELITE_MARKER):
            current = "BacktestElite"
            continue
        if s.startswith(PERSISTENCE_MARKER):
            current = "PersistenceSelected" if include_persistence else None
            continue
        if s.startswith("## "):
            current = None
            continue
        if not current or not s or s.startswith("#"):
            continue
        m = _CIK_RE.match(line)
        if m:
            tier_map.setdefault(m.group(1), current)
    return tier_map


def load_ciks(include_persistence: bool = True, existing_only: bool = False) -> list[str]:
    """Ordered CIK list. Default = sections 1+2+3. `existing_only` = section 1 only."""
    ciks: list[str] = []
    seen: set[str] = set()
    current: str | None = None
    for line in _path().read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(EXISTING_MARKER):
            current = "existing"
            continue
        if s.startswith(ELITE_MARKER):
            current = "elite"
            continue
        if s.startswith(PERSISTENCE_MARKER):
            current = "persistence"
            continue
        if s.startswith("## "):
            current = None
            continue
        if not current or not s or s.startswith("#"):
            continue
        if existing_only and current != "existing":
            continue
        if current == "persistence" and not include_persistence:
            continue
        m = _CIK_RE.match(line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            ciks.append(m.group(1))
    return ciks


def tier_for_cik(cik: str | int, tier_map: dict[str, str] | None = None) -> str:
    if tier_map is None:
        tier_map = load_tier_map()
    return tier_map.get(str(cik).zfill(10), "Other")
