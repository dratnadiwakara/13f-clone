"""YAML config loader. Single source of truth for paths + thresholds."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CLONE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = CLONE_ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def path(key: str) -> Path:
    val = load()["paths"][key]
    p = Path(val)
    return p if p.is_absolute() else REPO_ROOT / p
