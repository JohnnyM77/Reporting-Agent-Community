"""Read-only adapters onto existing portfolio/watchlist/agent-output data.

Same pattern as ``hindsight/adapters.py``: reads an existing file, never
imports or calls the agent that produced it, so Bob, Wally, Sally and Theo
run exactly as before whether Micky's Macro exists or not.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from shared.securities import strip_asx_suffix

REPO_ROOT = Path(__file__).resolve().parent.parent


def bare(ticker: str) -> str:
    return strip_asx_suffix(ticker).upper()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def holdings(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Ticker -> name, from tickers.yaml, ETFs excluded."""
    data = _load_yaml(repo_root / "tickers.yaml")
    etfs = {bare(t) for t in data.get("etf_tickers", []) or []}
    out: dict[str, str] = {}
    for key in ("asx", "lse", "sgx", "us"):
        for t, name in (data.get(key) or {}).items():
            t = bare(str(t).rstrip("."))
            if t and t not in etfs:
                out[t] = str(name)
    return out


def watchlist_membership(repo_root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """Ticker -> list of watchlist display names it appears in."""
    out: dict[str, list[str]] = {}
    wl_dir = repo_root / "watchlists"
    if not wl_dir.is_dir():
        return out
    for path in sorted(wl_dir.glob("*.yaml")):
        data = _load_yaml(path)
        name = str(data.get("name") or path.stem)
        for entry in data.get("tickers", []) or []:
            t = entry.get("ticker") if isinstance(entry, dict) else entry
            if not t:
                continue
            out.setdefault(bare(str(t)), []).append(name)
    return out


def _agent_tickers(repo_root: Path, rel: str, bucket_keys: tuple[str, ...]) -> set[str]:
    data = _load_json(repo_root / rel)
    out: set[str] = set()
    for key in bucket_keys:
        for item in data.get(key, []) or []:
            t = item.get("ticker") if isinstance(item, dict) else None
            if t:
                out.add(bare(str(t)))
    return out


def bob_coverage(repo_root: Path = REPO_ROOT) -> set[str]:
    return _agent_tickers(repo_root, "docs/data/bob.json", ("high_impact", "material", "fyi"))


def wally_flagged(repo_root: Path = REPO_ROOT) -> set[str]:
    data = _load_json(repo_root / "docs/data/wally.json")
    out: set[str] = set()
    for wl in (data.get("watchlists") or {}).values():
        for row in wl.get("flagged", []) or []:
            t = row.get("ticker")
            if t:
                out.add(bare(str(t)))
    return out


def sally_flagged(repo_root: Path = REPO_ROOT) -> set[str]:
    data = _load_json(repo_root / "docs/data/sally.json")
    return {bare(str(r.get("ticker"))) for r in data.get("flagged", []) or [] if r.get("ticker")}


def overlap_for(ticker: str, repo_root: Path = REPO_ROOT) -> list[str]:
    """Human-readable overlap tags for one ticker: held, which watchlists,
    and whether Bob/Wally/Sally are already watching it."""
    t = bare(ticker)
    tags: list[str] = []
    held = holdings(repo_root)
    if t in held:
        tags.append(f"already held ({held[t]})")
    for wl_name in watchlist_membership(repo_root).get(t, []):
        tags.append(f"on {wl_name}")
    if t in bob_coverage(repo_root):
        tags.append("Bob already covers this ticker's announcements")
    if t in wally_flagged(repo_root):
        tags.append("Wally has it flagged")
    if t in sally_flagged(repo_root):
        tags.append("Sally has it flagged")
    return tags
