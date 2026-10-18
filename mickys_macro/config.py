"""Config loading for Micky's Macro.

Source registry and taxonomy come from config/macro_sources.yaml and
config/macro_taxonomy.yaml; a handful of env vars override run behaviour
(store location, model, call caps, IMAP credentials, lookback windows).
Nothing personal lives in this file or in the YAML it reads -- raw email
content and extracted claims live only in the local store (see store.py).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = REPO_ROOT / "config" / "macro_sources.yaml"
TAXONOMY_PATH = REPO_ROOT / "config" / "macro_taxonomy.yaml"

MODEL_DEFAULT = "claude-sonnet-4-6"  # same default agent.py / hindsight use


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


@dataclass(frozen=True)
class SenderRule:
    match: str  # exact_sender | sender_local_prefix
    value: str
    domain: str = ""

    def matches(self, sender: str) -> bool:
        sender = (sender or "").strip().lower()
        if "@" not in sender:
            return False
        local, _, domain = sender.partition("@")
        if self.match == "exact_sender":
            return sender == self.value.strip().lower()
        if self.match == "sender_local_prefix":
            return local.startswith(self.value.strip().lower()) and domain == self.domain.strip().lower()
        return False


@dataclass(frozen=True)
class PrioritySource:
    name: str
    rules: tuple[SenderRule, ...]

    def matches(self, sender: str) -> bool:
        return any(r.matches(sender) for r in self.rules)


@dataclass(frozen=True)
class ResearchHouse:
    name: str
    kind: str


@dataclass(frozen=True)
class SourceRegistry:
    priority_sources: tuple[PrioritySource, ...]
    research_houses: tuple[ResearchHouse, ...]
    exclude_subject_patterns: tuple[re.Pattern, ...]
    theme_keywords: dict[str, tuple[str, ...]]

    def identify_sender(self, sender: str) -> str | None:
        """Priority-source name for *sender*, or None if it matches none.

        Never invents a sender -- this only classifies addresses already
        seen in the mailbox against the registry built from real addresses
        (see docs/MICKYS_MACRO_ARCHITECTURE.md section 1.5).
        """
        for src in self.priority_sources:
            if src.matches(sender):
                return src.name
        return None

    def is_excluded_subject(self, subject: str) -> bool:
        return any(p.search(subject or "") for p in self.exclude_subject_patterns)

    def keywords_for(self, text: str) -> list[str]:
        """Taxonomy category ids whose keywords appear in *text* (lowercased)."""
        t = (text or "").lower()
        return [cat for cat, kws in self.theme_keywords.items() if any(kw in t for kw in kws)]


def load_source_registry(path: Path | None = None) -> SourceRegistry:
    data = yaml.safe_load((path or SOURCES_PATH).read_text(encoding="utf-8")) or {}
    sources = []
    for entry in data.get("priority_sources", []) or []:
        rules = tuple(
            SenderRule(match=r["match"], value=r.get("value", ""), domain=r.get("domain", ""))
            for r in entry.get("rules", []) or []
        )
        sources.append(PrioritySource(name=entry["name"], rules=rules))
    houses = tuple(
        ResearchHouse(name=h["name"], kind=h.get("kind", "original_research"))
        for h in data.get("research_houses", []) or []
    )
    excludes = tuple(re.compile(p) for p in data.get("exclude_subject_patterns", []) or [])
    keywords = {
        cat: tuple(str(k).lower() for k in kws)
        for cat, kws in (data.get("theme_keywords", {}) or {}).items()
    }
    return SourceRegistry(
        priority_sources=tuple(sources),
        research_houses=houses,
        exclude_subject_patterns=excludes,
        theme_keywords=keywords,
    )


@dataclass(frozen=True)
class TaxonomyCategory:
    id: str
    label: str


def load_taxonomy(path: Path | None = None) -> tuple[TaxonomyCategory, ...]:
    data = yaml.safe_load((path or TAXONOMY_PATH).read_text(encoding="utf-8")) or {}
    return tuple(TaxonomyCategory(id=c["id"], label=c["label"]) for c in data.get("categories", []) or [])


@dataclass(frozen=True)
class RunConfig:
    """Env-driven run behaviour. See docs/MICKYS_MACRO_ARCHITECTURE.md."""

    store_dir: Path
    model: str
    max_llm_calls: int
    max_tokens: int
    imap_host: str
    imap_user: str
    imap_password: str
    incremental_lookback_days: int
    backfill_days: int
    max_emails_per_run: int
    reserve_calls_for_mapping: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "RunConfig":
        e = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return (e.get(name) or default).strip()

        return cls(
            store_dir=Path(get("MICKYS_MACRO_DATA_DIR") or str(REPO_ROOT / "mickys_macro_data")),
            model=get("MICKYS_MACRO_MODEL") or get("CLAUDE_MODEL") or MODEL_DEFAULT,
            max_llm_calls=int(get("MICKYS_MACRO_MAX_LLM_CALLS", "20")),
            max_tokens=int(get("MICKYS_MACRO_MAX_TOKENS", "8000")),
            imap_host=get("MICKYS_MACRO_IMAP_HOST", "imap.gmail.com"),
            imap_user=get("MICKYS_MACRO_IMAP_USER") or get("EMAIL_FROM") or get("EMAIL_USER"),
            imap_password=get("MICKYS_MACRO_IMAP_PASSWORD") or get("EMAIL_APP_PASSWORD"),
            incremental_lookback_days=int(get("MICKYS_MACRO_LOOKBACK_DAYS", "2")),
            backfill_days=int(get("MICKYS_MACRO_BACKFILL_DAYS", "365")),
            max_emails_per_run=int(get("MICKYS_MACRO_MAX_EMAILS_PER_RUN", "40")),
            # Claim extraction alone can fill the whole MAX_LLM_CALLS budget
            # during a backfill with a large unprocessed archive (the live
            # 2026-10-18 run: 25/25 calls went to extraction, 0 left for
            # trend mapping -- updated_dossiers and new_candidates came back
            # empty even though claims were extracted). Reserving a slice of
            # the budget for mapping/company-mapping/scoring guarantees every
            # run makes forward progress on dossiers, not just on ingestion.
            reserve_calls_for_mapping=int(get("MICKYS_MACRO_RESERVE_CALLS_FOR_MAPPING", "8")),
        )
