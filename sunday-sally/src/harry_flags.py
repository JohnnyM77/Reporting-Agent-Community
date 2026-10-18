"""Harry Hindsight's hand-off: ``data/harry_flags.yaml`` at the repo root.

A ticker listed there has had its thesis read as BROKEN by Harry, and Sally
runs a full sell analysis on it this week whether or not it is near a 52-week
high. Harry removes the ticker when a later review reads the thesis as back in
line. A missing or unreadable file means no flags: Sally never fails on it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .pathing import repo_root

REL = Path("data") / "harry_flags.yaml"


def load_harry_flags(root: Path | None = None) -> dict[str, dict]:
    path = (root or repo_root()) / REL
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"[sally] WARNING: could not read {REL} ({exc}); no Harry flags this run")
        return {}
    flags = data.get("flags") or {}
    out = {}
    for ticker, flag in flags.items():
        t = str(ticker).strip().upper().removesuffix(".AX")
        if t:
            out[t] = flag if isinstance(flag, dict) else {}
    return out
