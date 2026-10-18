"""Esther's pre-output checklist (spec s.18). Code checks what code can check;
what only the model can judge is reported as the model's own self-check, and
labelled that way, never as a pass."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from esther.prompts import BANNED_PHRASES

DASHES = ("—", "–", "‒", "―")  # em, en, figure, horizontal bar

FULL_WORDS = (300, 500)
QUICK_WORDS = (100, 200)
# Over the limit by this much is a hard fail worth a repair call; a few words over is a warning.
HARD_OVER = 1.10


def scrub_dashes(text: str) -> str:
    """Remove every em/en dash. Number ranges keep a hyphen; prose gets a comma."""
    if not isinstance(text, str):
        return text
    text = re.sub(r"(\d)\s*[–—‒―]\s*(\d)", r"\1-\2", text)
    text = re.sub(r"\s*[—―]\s*", ", ", text)
    text = re.sub(r"\s+[–‒]\s+", ", ", text)
    text = re.sub(r"[–‒]", "-", text)
    return text.replace(" ,", ",").replace(",,", ",")


def scrub_all(obj: Any) -> Any:
    """scrub_dashes over every string in a JSON-like structure."""
    if isinstance(obj, str):
        return scrub_dashes(obj)
    if isinstance(obj, list):
        return [scrub_all(v) for v in obj]
    if isinstance(obj, dict):
        return {k: scrub_all(v) for k, v in obj.items()}
    return obj


def word_count(text: str) -> int:
    body = re.sub(r"^#+\s.*$", "", text or "", flags=re.MULTILINE)  # headings don't count
    return len(re.findall(r"[A-Za-z0-9$%.']+", body))


def banned_found(text: str) -> list[str]:
    low = (text or "").lower()
    return [p for p in BANNED_PHRASES if re.search(r"\b" + re.escape(p) + r"\b", low)]


# Things that belong in JM's private notes, never on a public Simply Wall St narrative about a stock he owns.
PRIVATE_TALK = (
    r"\btrim(?:ming)?\b", r"\bsell(?:ing)? (?:some|down|out)\b", r"\bposition size\b", r"\boverweight\b",
    r"\b\d+(?:\.\d+)?% of (?:my|the) (?:portfolio|book)\b", r"\bbig position\b", r"\blargest position\b",
    r"\bmy (?:average|buy) (?:cost|price)\b", r"\bwhat i paid\b",
)


def private_talk_found(text: str) -> list[str]:
    low = (text or "").lower()
    return [m.group(0) for pat in PRIVATE_TALK for m in [re.search(pat, low)] if m]


@dataclass
class QCResult:
    checks: list[tuple[str, bool, str]] = field(default_factory=list)  # (item, passed, note)
    hard_errors: list[str] = field(default_factory=list)  # worth one repair call
    model_self_check: dict = field(default_factory=dict)

    def add(self, item: str, passed: bool, note: str = "", hard: bool = False) -> None:
        self.checks.append((item, passed, note))
        if hard and not passed:
            self.hard_errors.append(f"{item}: {note}" if note else item)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


REQUIRED_FIELDS = ("title", "narrative", "narrative_case", "base_figures", "what_changed", "so_what",
                   "watching_next", "what_would_change_my_mind", "thesis_check", "challenge", "evidence",
                   "statutory_vs_underlying", "publish_recommendation")


def check(analysis: dict, valuation_warnings: list[str] | None = None) -> QCResult:
    qc = QCResult(model_self_check=dict(analysis.get("self_check") or {}))

    missing = [f for f in REQUIRED_FIELDS if not analysis.get(f)]
    qc.add("All sections present", not missing, ", ".join(missing), hard=True)

    narrative = analysis.get("narrative") or ""
    n = word_count(narrative)
    lo, hi = FULL_WORDS
    qc.add("Narrative under ~500 words", n <= hi, f"{n} words", hard=n > hi * HARD_OVER)
    if n < lo:
        qc.add("Narrative not padded, but has enough to say", False,
               f"{n} words, under {lo} (fine if there is genuinely less to say)")
    quick = (analysis.get("quick_update") or {}).get("narrative") or ""
    if quick:
        q = word_count(quick)
        qc.add("Quick update 100-200 words", QUICK_WORDS[0] * 0.8 <= q <= QUICK_WORDS[1] * HARD_OVER, f"{q} words")

    blob = _all_text(analysis)
    dashes = sum(blob.count(d) for d in DASHES)
    scrubbed = int(analysis.get("_dashes_scrubbed") or 0)
    qc.add("Zero em dashes", dashes == 0,
           f"{dashes} found" if dashes else (f"{scrubbed} scrubbed from the model's draft" if scrubbed else ""))

    banned = banned_found(narrative + " " + ((analysis.get("quick_update") or {}).get("narrative") or "")
                          + " " + (analysis.get("title") or ""))
    qc.add("No banned phrases", not banned, ", ".join(banned), hard=bool(banned))

    svu = (analysis.get("statutory_vs_underlying") or "").strip()
    qc.add("Statutory and underlying separated", bool(svu), "" if svu else "missing", hard=not svu)
    qc.add("Cash flow and balance sheet considered", bool((analysis.get("cash_flow_and_balance_sheet") or "").strip()))
    claims = analysis.get("management_claims_tested") or []
    qc.add("Management narrative challenged", bool(claims), f"{len(claims)} claim(s) tested")

    ev = analysis.get("evidence") or []
    qc.add("Evidence trail present", len(ev) >= 3, f"{len(ev)} item(s)", hard=len(ev) == 0)
    qc.add("Clear 'So what?'", bool((analysis.get("so_what") or "").strip()))
    qc.add("Clear 'What I'm watching next'", bool(analysis.get("watching_next")))

    low_title = (analysis.get("title") or "").lower()
    generic = bool(re.search(r"\b(fy|hy|h1|h2)\s?\d{2}\b.*\bresults?\b|^\w+ (full|half)[- ]year results", low_title))
    qc.add("Title expresses an insight, not 'XYZ FY26 Results'", not generic, analysis.get("title") or "")

    private = private_talk_found(narrative)
    qc.add("Public copy keeps sizing and selling talk private", not private, ", ".join(private), hard=bool(private))
    vw = valuation_warnings or []
    qc.add("Valuation inputs sane", not vw, "; ".join(vw))
    qc.add("Valuation driven by explicit assumptions", True, "value computed in code from the three SWS inputs")
    return qc


def _all_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return " ".join(_all_text(v) for v in obj)
    if isinstance(obj, dict):
        return " ".join(_all_text(v) for v in obj.values())
    return ""
