"""What may leave the private repo, and what may not.

Two places publish to the outside world: the GitHub Pages site (docs/ plus
Theo's slides) and the community edition (a scrubbed copy of this repo in a
separate public repo). Both run through this module.

The rule is narrow on purpose. Johnny is happy for people to know what he
holds, how the decisions went (IRR, multiple, % up or down), his watchlists,
his family and his employers. What must never be public is anything that
lets someone work out how much money is involved:

* dollar amounts of positions (cost, value, proceeds, dividends received)
* share counts
* position weights (share of book / capital), because a weight plus any one
  dollar figure gives the size of the whole portfolio

plus one family member's email address (matched by its domain).

Two tools:

* ``scrub_text`` / ``scrub_obj`` rewrite free text so a model-written sentence
  like "an accidental 9% overweight" becomes "an accidental x% overweight".
  Used where Harry writes the public JSON, and on the staged Pages site.
* ``scan_tree`` is the guard. It never rewrites anything, it only reports,
  and the caller fails the run on any hard finding. It also checks every
  number from the private IRR workbook (the canary list) against the output,
  so an exact figure that slips past the patterns is still caught.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Keys that carry a position weight. Dropped from public JSON, and a hard
# failure if the guard finds one.
BANNED_KEYS = frozenset({"weight_of_book_pct", "weight_if_new", "value_weight", "cost_weight"})

_OWNER = r"(?:the|his|your|my|johnny's|jm's|johnny’s|jm’s)"

# "9% of portfolio", "5% of capital", "9% overweight", "3% sizing",
# "a 3% weight". "of book" needs an owner word so a bank's "25% of book"
# (its loan book) is left alone.
_PCT_BEFORE = re.compile(
    r"(?<![\w.])((?:\d+(?:\.\d+)?\s?%?\s?(?:-|–|to)\s?)?\d+(?:\.\d+)?)(\s?%)(?=\s+(?:"
    rf"of\s+(?:{_OWNER}\s+)?(?:portfolio|capital\b|net\s+worth|capital\s+committed)"
    rf"|of\s+{_OWNER}\s+book\b"
    r"|overweight|underweight|weight\b|weighting|sizing|position\s+size|allocation"
    r"))",
    re.IGNORECASE,
)
# "weight of 9%", "sizing at 3%", "share of book: 9%"
_PCT_AFTER = re.compile(
    r"((?:weight(?:ing)?|sizing|position\s+size|share\s+of\s+(?:the\s+)?(?:book|portfolio|capital))"
    r"\s*(?:of|at|to|is|was|:|=|near|around|about|roughly|~)?\s*(?:about\s+|around\s+|roughly\s+|~)?)"
    r"(\d+(?:\.\d+)?)(\s?%)",
    re.IGNORECASE,
)
_SHARES = re.compile(r"\b(?:\d{1,3}(?:,\d{3})+|\d{4,})(?=\s+shares\b)", re.IGNORECASE)
# $12,345 style. Company-scale figures ("$4,180m", "$2.3bn") are not
# positions, so a scale suffix exempts the number.
_DOLLAR = re.compile(
    r"((?:A|S|SG|US|AU)?\$\s?)(\d{1,3}(?:,\d{3})+)(\.\d+)?"
    r"(?!\s?(?:m|bn|b|k|mn|million|billion|thousand)\b)(?!\d|,\d)",
    re.IGNORECASE,
)
_DOLLAR_K = re.compile(r"((?:A|S|SG|US|AU)?\$\s?)(\d+(?:\.\d+)?)k\b", re.IGNORECASE)
# Built from parts so this file does not trip its own check.
_FAMILY_DOMAIN = re.compile("myerscough" + r"s\.com", re.IGNORECASE)
_CTO = re.compile(
    r"brother[^.\n]{0,80}\b(?:CTO|chief\s+technology\s+officer)\b"
    r"|\b(?:CTO|chief\s+technology\s+officer)\b[^.\n]{0,80}\bbrother",
    re.IGNORECASE,
)

PRIVATE_START = "<!-- private:start -->"
PRIVATE_END = "<!-- private:end -->"
_PRIVATE_BLOCK = re.compile(
    re.escape(PRIVATE_START) + r".*?" + re.escape(PRIVATE_END) + r"\n?", re.DOTALL
)


# ---------------------------------------------------------------------------
# Scrubbing
# ---------------------------------------------------------------------------


def scrub_text(text: str, *, dollars: bool = True, min_dollars: int = 0) -> str:
    """Remove weights (and by default position-sized money) from free text.

    Replacements are a bare ``x`` ("$x", "x shares", "x% of portfolio") so the
    result is still valid inside YAML frontmatter: a scalar may not start with
    ``[``. ``min_dollars`` leaves smaller comma figures alone, for prose where
    a "$2,230 of turnover" is the point of the story rather than a position.
    """
    if not text:
        return text
    out = _PCT_BEFORE.sub(lambda m: "x" + m.group(2), text)
    out = _PCT_AFTER.sub(lambda m: m.group(1) + "x" + m.group(3), out)
    if dollars:
        out = _SHARES.sub("x", out)

        def _money(m: re.Match[str]) -> str:
            if int(m.group(2).replace(",", "")) < min_dollars:
                return m.group(0)
            return m.group(1) + "x"

        out = _DOLLAR.sub(_money, out)
        out = _DOLLAR_K.sub(lambda m: m.group(1) + "x", out)
    return out


def scrub_obj(obj: Any, *, dollars: bool = True) -> Any:
    """Recursively drop weight keys and scrub every string."""
    if isinstance(obj, dict):
        return {k: scrub_obj(v, dollars=dollars) for k, v in obj.items() if k not in BANNED_KEYS}
    if isinstance(obj, list):
        return [scrub_obj(v, dollars=dollars) for v in obj]
    if isinstance(obj, str):
        return scrub_text(obj, dollars=dollars)
    return obj


def strip_private_blocks(text: str) -> str:
    """Remove ``<!-- private:start --> ... <!-- private:end -->`` blocks."""
    return _PRIVATE_BLOCK.sub("", text)


# ---------------------------------------------------------------------------
# Canaries: the real numbers, from the private workbook
# ---------------------------------------------------------------------------


def load_canaries(path: Path) -> list[int]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().replace(",", "")
        if line.isdigit():
            out.append(int(line))
    return sorted(set(out))


def canary_regex(canaries: Iterable[int]) -> re.Pattern[str] | None:
    """Match a ledger number as a standalone figure.

    ``987,654`` and ``987654`` both match. Four-digit numbers only match in
    their comma form: a bare ``4444`` is far more likely to be a colour code or
    part of an embedded image than a share count. Letters, ``#``, ``/``, ``+``
    and ``=`` on either side mean it is part of a token, not a figure.
    """
    forms: set[str] = set()
    for n in canaries:
        forms.add(f"{n:,}")
        if n >= 10_000:
            forms.add(str(n))
    if not forms:
        return None
    alt = "|".join(sorted((re.escape(f) for f in forms), key=len, reverse=True))
    return re.compile(rf"(?<![\w,.#/+=-])(?:{alt})(?![\w#/+=]|,\d)")


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    path: str
    rule: str
    snippet: str
    hard: bool = True

    def __str__(self) -> str:
        level = "LEAK" if self.hard else "warn"
        return f"[{level}] {self.path}: {self.rule}: {self.snippet}"


TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".html", ".txt", ".csv", ".py", ".ps1", ".sh", ".toml", ".cfg"}


def _snip(text: str, m: re.Match[str]) -> str:
    a, b = max(0, m.start() - 40), min(len(text), m.end() + 40)
    return text[a:b].replace("\n", " ")


def _walk_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


def glob_match(rel: str, pattern: str) -> bool:
    """Match a posix path against a glob where ``*`` stays inside one folder
    and ``**`` crosses folders. (``fnmatch`` and ``Path.match`` both let a
    bare ``*.md`` match at any depth, which is not what a scope rule wants.)"""
    rx = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            rx += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            rx += ".*"
            i += 2
        elif pattern[i] == "*":
            rx += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            rx += "[^/]"
            i += 1
        else:
            rx += re.escape(pattern[i])
            i += 1
    return re.fullmatch(rx, rel) is not None


def _allowed(snippet: str, allow: list[str]) -> bool:
    return any(a in snippet for a in allow)


def scan_text(
    rel: str,
    text: str,
    *,
    personal: bool,
    canary_re: re.Pattern[str] | None,
    cto: bool,
    allow: list[str],
    canary_hard: bool = False,
) -> list[Finding]:
    """Check one file's text.

    ``personal`` files are the ones that talk about Johnny's own positions
    (Harry, Theo, the theses). Those get the money-shape rules. Everything
    else (Bob's announcement summaries, Ned's news) legitimately quotes share
    counts and dollar figures from company filings, so only the exact canary
    numbers apply there, and as warnings.
    """
    found: list[Finding] = []

    def add(rule: str, m: re.Match[str], hard: bool = True) -> None:
        s = _snip(text, m)
        if not _allowed(s, allow):
            found.append(Finding(rel, rule, s, hard))

    for m in _FAMILY_DOMAIN.finditer(text):
        add("family email domain", m)
    if cto:
        for m in _CTO.finditer(text):
            add("relative inside an investee company", m)
    if rel.endswith(".json"):
        try:
            keys = set(_walk_keys(json.loads(text)))
        except ValueError:
            keys = set()
        for k in sorted(keys & BANNED_KEYS):
            found.append(Finding(rel, "weight field", k))
    for m in _PCT_BEFORE.finditer(text):
        add("position weight", m, hard=personal)
    for m in _PCT_AFTER.finditer(text):
        add("position weight", m, hard=personal)
    if personal:
        for m in _SHARES.finditer(text):
            add("share count", m)
        for m in _DOLLAR.finditer(text):
            if int(m.group(2).replace(",", "")) >= 10_000:
                add("dollar amount", m)
        for m in _DOLLAR_K.finditer(text):
            add("dollar amount ($k)", m)
    if canary_re is not None:
        for m in canary_re.finditer(text):
            add("exact ledger number", m, hard=personal or canary_hard)
    return found


def scan_tree(
    root: Path,
    *,
    personal_globs: Iterable[str],
    canaries: Iterable[int] = (),
    cto: bool = False,
    allow: Iterable[str] = (),
    skip_globs: Iterable[str] = (),
    canary_hard: bool = False,
) -> list[Finding]:
    root = Path(root)
    canary_re = canary_regex(canaries)
    personal_globs = list(personal_globs)
    skip_globs = list(skip_globs)
    allow = [a for a in allow if a.strip()]
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or any(glob_match(rel, g) for g in skip_globs):
            continue
        personal = any(glob_match(rel, g) for g in personal_globs)
        text = path.read_text(encoding="utf-8", errors="ignore")
        findings += scan_text(rel, text, personal=personal, canary_re=canary_re, cto=cto, allow=allow,
                              canary_hard=canary_hard)
    return findings


def load_allowlist(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [
        line.rstrip("\n")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
