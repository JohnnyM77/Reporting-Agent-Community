# ned/source_quality.py
#
# Source tiers for Ned's news scan.
#
# Not every outlet is equal. Kalkine (and sites like it) machine-rewrite every
# ASX announcement into a headline stuffed with "buy-back", "revenue",
# "results" and the like, so on keyword scoring alone they outrank real
# journalism and take the dashboard's two-per-company slots. Tiers fix that
# without hiding anything:
#
#   tier 1  quality journalism (AFR, Livewire, Ausbiz, Market Index ...)
#   tier 2  fine but promotional, and the default for anything unlisted
#   tier 3  AI rewrite mills (Kalkine ...): capped at LOW, no LLM summary,
#           collapsed into one "wire rewrites" line at the bottom of the email
#
# The lists live in media_sources.yaml under `source_tiers:` so they can be
# edited without touching code. Matching is a case-insensitive substring test
# against the publisher name, the publisher URL and the article link.

from __future__ import annotations

import re
from typing import Any

DEFAULT_TIER = 2
LOW_QUALITY_TIER = 3

# Used when media_sources.yaml has no source_tiers block, so the Kalkine fix
# never silently disappears with a config edit.
_FALLBACK_TIERS: dict[int, list[str]] = {
    1: [],
    3: ["kalkine"],
}

_TIER_KEYS = {"tier1": 1, "tier2": 2, "tier3": 3}

# Google News titles end " - Publisher". Only strip a short trailing segment so
# a headline that genuinely contains " - " keeps its body.
_PUBLISHER_SUFFIX = re.compile(r"\s+[-–—|]\s+([^-–—|]{2,60})$")


def load_tiers(media_config: dict | None) -> dict[int, list[str]]:
    """Read `source_tiers:` from media_sources.yaml into {tier: [patterns]}."""
    raw = (media_config or {}).get("source_tiers") or {}
    tiers: dict[int, list[str]] = {}
    for key, patterns in raw.items():
        tier = _TIER_KEYS.get(str(key).lower())
        if tier is None:
            continue
        tiers[tier] = [str(p).strip().lower() for p in (patterns or []) if str(p).strip()]
    if not tiers:
        return {k: list(v) for k, v in _FALLBACK_TIERS.items()}
    # Kalkine stays tier 3 even if someone empties the list by accident.
    tiers.setdefault(3, [])
    if "kalkine" not in tiers[3]:
        tiers[3].append("kalkine")
    return tiers


def split_publisher_suffix(title: str) -> tuple[str, str]:
    """'Brambles lifts guidance - Kalkine Media' -> ('Brambles lifts guidance', 'Kalkine Media')."""
    m = _PUBLISHER_SUFFIX.search(title or "")
    if not m:
        return title or "", ""
    return title[: m.start()].rstrip(), m.group(1).strip()


def classify_tier(hit: dict, tiers: dict[int, list[str]]) -> int:
    """Return the tier for a hit. Tier 3 wins over tier 1 on a conflict:
    a rewrite mill hosted on a respectable domain is still a rewrite mill."""
    if hit.get("tier_override") in (1, 2, 3):
        return int(hit["tier_override"])
    haystack = " ".join(
        str(hit.get(k, "")) for k in ("publisher", "publisher_url", "url", "source")
    ).lower()
    for tier in (3, 1, 2):
        for pattern in tiers.get(tier, []):
            if pattern and pattern in haystack:
                return tier
    return DEFAULT_TIER


def apply_source_tiers(hits: list[dict], tiers: dict[int, list[str]]) -> list[dict]:
    """Stamp `tier` on every hit (in place) and return the list."""
    for h in hits:
        h["tier"] = classify_tier(h, tiers)
    return hits


# ----------------------------
# Same-story collapse
# ----------------------------
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "at", "by",
    "with", "as", "is", "its", "it", "from", "after", "asx", "ltd", "limited",
    "shares", "share", "stock", "why", "how", "what",
}


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in _STOP and len(w) > 1}


def _similar(a: set[str], b: set[str], threshold: float) -> bool:
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= threshold


def collapse_duplicates(hits: list[dict], threshold: float = 0.6) -> list[dict]:
    """Collapse the same story told by several outlets about the same company.

    Keeps the best-tier version (tier 1 beats 2 beats 3; first seen breaks a
    tie) and records the others on it as `also_covered_by`. Identical URLs are
    always merged, whatever the wording.
    """
    kept: list[dict] = []
    for h in hits:
        ticker = (h.get("tickers") or [""])[0]
        toks = _tokens(h.get("title", ""))
        match = None
        for k in kept:
            if (k.get("tickers") or [""])[0] != ticker:
                continue
            if (h.get("url") and h.get("url") == k.get("url")) or _similar(
                toks, k["_tokens"], threshold
            ):
                match = k
                break
        if match is None:
            h["_tokens"] = toks
            h.setdefault("also_covered_by", [])
            h.setdefault("merged_seen_keys", [])
            kept.append(h)
            continue
        if h.get("tier", DEFAULT_TIER) < match.get("tier", DEFAULT_TIER):
            # Swap the new, better-tier hit into the kept slot.
            idx = kept.index(match)
            h["_tokens"] = toks
            h["also_covered_by"] = _add_name(match.get("also_covered_by", []), _outlet(match), _outlet(h))
            h["merged_seen_keys"] = match.get("merged_seen_keys", []) + [match.get("seen_key", "")]
            kept[idx] = h
            continue
        match["also_covered_by"] = _add_name(match["also_covered_by"], _outlet(h), _outlet(match))
        # The collapsed copy goes into seen-state with the winner, so it can't
        # come back on its own tomorrow.
        match["merged_seen_keys"].append(h.get("seen_key", ""))
    for k in kept:
        k.pop("_tokens", None)
    return kept


def _add_name(names: list[str], name: str, winner_name: str) -> list[str]:
    if name and name != winner_name and name not in names:
        return names + [name]
    return names


def _outlet(hit: dict) -> str:
    return hit.get("publisher") or hit.get("source") or ""


def low_quality_rollup(hits: list[dict]) -> list[tuple[str, list[tuple[str, int]]]]:
    """Group tier-3 hits as [(publisher, [(ticker, count), ...]), ...] for the
    one-line email summary, busiest publisher first."""
    by_pub: dict[str, dict[str, int]] = {}
    for h in hits:
        if h.get("tier") != LOW_QUALITY_TIER:
            continue
        pub = _outlet(h) or "Unknown"
        ticker = (h.get("tickers") or ["?"])[0]
        by_pub.setdefault(pub, {})
        by_pub[pub][ticker] = by_pub[pub].get(ticker, 0) + 1
    out = []
    for pub, counts in by_pub.items():
        out.append((pub, sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))))
    out.sort(key=lambda p: -sum(c for _, c in p[1]))
    return out


def settings_from(media_config: dict | None) -> dict[str, Any]:
    """Small helper so main.py reads one place for tier-related knobs."""
    cfg = (media_config or {}).get("dedupe") or {}
    return {"similarity": float(cfg.get("similarity", 0.6))}
