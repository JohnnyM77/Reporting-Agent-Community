"""Where Micky's Macro keeps its research: ``mickys_macro_data/`` at the repo
root (gitignored), same pattern as ``hindsight_data/`` and ``esther_data/``.

Raw email content and extracted claims are research material gathered from
Johnny's own inbox -- not something to commit to a public repo. The public
dashboard (``docs/data/mickys_macro.json``) carries only the public-safe
summary built in ``web.py``.

Refuses to start if the directory would be tracked by the public repo,
same safety check Harry's store uses, duplicated here (not imported from
``hindsight``) so this agent has no import-time dependency on that one --
each agent owns its own store, per the repo's "no coupling" convention
(see CLAUDE.md's Slinger/Bob note).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

REPO_ROOT = Path(__file__).resolve().parent.parent

TABLES = (
    "email_record",
    "claim",
    "trend_dossier",
    "trend_score",
    "company_candidate",
    "processing_log",
    "seen_message",
    "kv",
)


class StoreConfigError(RuntimeError):
    """The store is not configured safely. Nothing has been written."""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _ignored_by_public_repo(path: Path, repo_root: Path) -> bool:
    probe = path / "probe.txt"
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "check-ignore", "-q", str(probe)],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def _assert_not_tracked(path: Path, repo_root: Path) -> None:
    if _is_within(path, repo_root) and (repo_root / ".git").exists():
        if not _ignored_by_public_repo(path, repo_root):
            raise StoreConfigError(
                f"Refusing to use {path} as the Micky's Macro store: it sits inside "
                f"the public repo and is not gitignored. Research content would be committed."
            )


class Store:
    """Filesystem layout + SQLite. Create via :func:`open_store`."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = root / "mickys_macro.db"
        self.conn = sqlite3.connect(self.db_path)
        for table in TABLES:
            self.conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} ("
                "id TEXT PRIMARY KEY, created_at TEXT, data TEXT)"
            )
        self.conn.commit()

    # -- generic record access --------------------------------------------

    def put(self, table: str, record: BaseModel) -> None:
        d = record.model_dump(mode="json")
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} (id, created_at, data) VALUES (?,?,?)",
            (d["id"], d.get("created_at", ""), json.dumps(d)),
        )
        self.conn.commit()

    def get(self, table: str, model: Type[T], record_id: str) -> T | None:
        row = self.conn.execute(f"SELECT data FROM {table} WHERE id=?", (record_id,)).fetchone()
        return model.model_validate(json.loads(row[0])) if row else None

    def all(self, table: str, model: Type[T]) -> list[T]:
        rows = self.conn.execute(f"SELECT data FROM {table} ORDER BY created_at").fetchall()
        return [model.model_validate(json.loads(r[0])) for r in rows]

    def find(self, table: str, model: Type[T], **equals: Any) -> list[T]:
        """In-process filter (tables are small; no need for SQL predicates
        per field the way hindsight's ticker/status columns do it)."""
        out = []
        for rec in self.all(table, model):
            d = rec.model_dump(mode="json")
            if all(d.get(k) == v for k, v in equals.items()):
                out.append(rec)
        return out

    # -- dedup: Gmail message-id -> already processed ------------------------

    def seen_message(self, message_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen_message WHERE id=?", (message_id,)).fetchone()
        return row is not None

    def mark_message_seen(self, message_id: str, when: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO seen_message (id, created_at, data) VALUES (?,?,?)",
            (message_id, when, json.dumps({"message_id": message_id})),
        )
        self.conn.commit()

    # -- small key/value state (last-run markers) -----------------------------

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT data FROM kv WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO kv (id, created_at, data) VALUES (?,?,?)",
            (key, "", json.dumps(value)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def open_store(env: dict[str, str] | None = None, repo_root: Path = REPO_ROOT) -> Store:
    e = os.environ if env is None else env
    root = Path((e.get("MICKYS_MACRO_DATA_DIR") or str(repo_root / "mickys_macro_data")).strip())
    _assert_not_tracked(root, repo_root)
    return Store(root)
