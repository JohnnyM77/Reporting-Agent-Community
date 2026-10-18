"""Where Esther keeps her previous runs, for change detection (spec s.13).

Narratives carry JM's views and his holdings, and this repo is public, so the
store must never be a tracked path. Default is ``esther_data/`` (gitignored);
the workflow points ESTHER_STORE_DIR at the private repo checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from esther.context import REPO_ROOT


class StoreConfigError(RuntimeError):
    pass


def store_dir(root: Path = REPO_ROOT) -> Path:
    raw = os.environ.get("ESTHER_STORE_DIR") or str(root / "esther_data")
    path = Path(raw).resolve()
    _refuse_tracked(path, root)
    return path


def _refuse_tracked(path: Path, root: Path) -> None:
    """A path inside this repo must be gitignored, or we'd publish JM's views."""
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return  # outside the public checkout (e.g. the private repo): fine
    try:
        probe = path / "probe.json"
        rc = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(probe)],
                            capture_output=True).returncode
    except Exception:
        return  # no git (unit tests in a tmp dir): nothing can be committed anyway
    if rc == 1:
        raise StoreConfigError(f"{path} is inside the public repo and not gitignored; refusing to write there")


def load_previous(ticker: str, root: Path = REPO_ROOT) -> Optional[dict]:
    path = store_dir(root) / ticker / "latest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save(ticker: str, record: dict, root: Path = REPO_ROOT) -> Path:
    d = store_dir(root) / ticker
    d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(record, indent=1, default=str, ensure_ascii=False)
    (d / "latest.json").write_text(body, encoding="utf-8")
    dated = d / f"{record.get('date', 'undated')}.json"
    dated.write_text(body, encoding="utf-8")
    return dated
