"""Harry's flags for Sally: ``data/harry_flags.yaml``.

When Harry reads a holding's thesis as BROKEN, he writes the ticker here and
Sally puts it through a full sell analysis on her next run, whether or not it
is anywhere near a 52-week high. When a later Harry review reads the thesis as
back in line (THESIS INTACT or STRENGTHENED), the flag is removed. WEAKENED
and CHANGED leave an existing flag where it is and do not raise a new one.

The file is public (it sits in the repo, like the dashboard card that already
shows the same verdict), so it carries the ticker, the date and a one-line
reason only: no position data, no bias read.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import yaml

REL = Path("data") / "harry_flags.yaml"
HEADER = (
    "# Written by Harry Hindsight. Read by Selling Sally.\n"
    "# A ticker here gets a full sell analysis from Sally on her next run.\n"
    "# Harry adds a ticker when he reads its thesis as BROKEN and removes it\n"
    "# when a later review reads the thesis as back in line.\n"
    "# Safe to edit by hand: delete a ticker to stop the sell reviews.\n"
)
CLEARS = ("THESIS INTACT", "STRENGTHENED")


def load(repo_root: Path) -> dict[str, Any]:
    path = repo_root / REL
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    data.setdefault("flags", {})
    return data


def _classification(b: dict) -> str | None:
    """Harry's read of the thesis: the model's, else the git-history detector's."""
    out = b.get("output")
    if out is not None and out.thesis_test:
        if out.thesis_test.classification == "BROKEN":
            return "BROKEN"
        model = out.thesis_test.classification
    else:
        model = None
    tc = b.get("tc")
    if tc is not None and tc.classification == "BROKEN":
        return "BROKEN"
    return model


def update(repo_root: Path, reports: list[dict], holdings: set[str], today: dt.date) -> tuple[list[str], list[str]]:
    """Apply this run's reports to the flag file. Returns ``(raised, cleared)``."""
    data = load(repo_root)
    flags: dict[str, Any] = data["flags"]
    raised, cleared = [], []
    for b in reports:
        t = b.get("ticker")
        if b.get("status") != "OK" or not t or t not in holdings:
            continue
        cls = _classification(b)
        out = b["output"]
        if cls == "BROKEN":
            if t not in flags:
                raised.append(t)
            prev = flags.get(t) or {}
            flags[t] = {
                "reason": "Harry Hindsight reads the thesis as BROKEN",
                "raised": prev.get("raised") or today.isoformat(),
                "last_confirmed": today.isoformat(),
                "severity": out.severity,
                "verdict": " ".join(str(out.verdict).split())[:240],
            }
        elif cls in CLEARS and t in flags:
            flags.pop(t)
            cleared.append(t)
    if raised or cleared or any(flags.get(t, {}).get("last_confirmed") == today.isoformat() for t in flags):
        data["updated"] = today.isoformat()
        path = repo_root / REL
        path.parent.mkdir(parents=True, exist_ok=True)
        body = yaml.safe_dump({"updated": data["updated"], "flags": dict(sorted(flags.items()))},
                              sort_keys=False, allow_unicode=True)
        path.write_text(HEADER + body, encoding="utf-8")
    return raised, cleared
