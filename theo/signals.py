"""Signals from the other agents, turned into questions Theo will not drop.

Sally flags a holding as a trim candidate. You decline. That decline is the
single most important thing in the whole system and it is the one thing that
never gets written down — a year later it is remembered as conviction rather
than as "I waved off a valuation flag three times running".

So a signal from another agent opens a **question** against the thesis. It
does not block anything: a blocking prompt gets clicked through, and then you
have trained yourself to ignore it. Instead the question stays open, and an
open question is itself a drift finding. Silence gets recorded.

Answering means adding a dated review to the thesis file with the trigger and
the decision on it. Declining is a perfectly good answer — once. Declining the
same signal three times without ever writing down what *would* change your
mind is an alert, because at that point the position is being defended rather
than held.

This module only ever *reads* the other agents' dashboard JSON. Sally is not
modified and does not know Theo exists.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path
from typing import Iterable, Sequence

from .drift import ALERT, Finding, WARN
from .thesis import Thesis

DASHBOARD_DIR = Path("docs/data")

SALLY_TRIM = "SALLY_TRIM"
SALLY_REVIEW = "SALLY_REVIEW"
HARRY_BROKEN = "HARRY_BROKEN"
# Bob picked up a full-year result for a holding. The annual refresh is the one
# review Theo actively invites you to — answered, like any other, by a dated
# review (trigger: ANNUAL_REPORT). Declining is fine; silence is recorded.
BOB_ANNUAL = "ANNUAL_REPORT"

# Decline this many times without writing a kill condition and it stops being
# a judgement call and starts being a habit.
REFUSAL_LIMIT = 3


@dataclasses.dataclass
class Signal:
    """Something another agent noticed, addressed to a ticker."""

    source: str
    ticker: str
    kind: str
    detail: str = ""
    date: dt.date | None = None
    question: str = ""

    @property
    def label(self) -> str:
        return f"{self.source}: {self.kind.replace('_', ' ').lower()}"


def _date(value) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def from_sally(path: str | Path | None = None) -> list[Signal]:
    """Read Sally's flagged holdings out of her dashboard JSON."""
    data = _load_json(Path(path) if path else DASHBOARD_DIR / "sally.json")
    when = _date(data.get("last_run"))
    out: list[Signal] = []

    for row in data.get("flagged", []):
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        verdict = str(row.get("sally_verdict", "")).strip()
        tier = str(row.get("alert_tier", "")).strip()
        kind = SALLY_TRIM if "trim" in verdict.lower() else SALLY_REVIEW

        bits = [b for b in (verdict, tier) if b]
        pe = row.get("trailing_pe")
        pct = row.get("valuation_percentile")
        if pe:
            bits.append(f"PE {float(pe):.0f}x")
        if pct:
            bits.append(f"{float(pct) * 100:.0f}th valuation percentile")

        out.append(
            Signal(
                source="Sally",
                ticker=ticker,
                kind=kind,
                detail=" · ".join(bits),
                date=when,
                question=(
                    "Sally says trim. You are not going to. What would have to be "
                    "true about the price for you to change that answer — and is "
                    "that written down as a kill condition anywhere?"
                    if kind == SALLY_TRIM
                    else "Sally has flagged this for review. What does she see that "
                    "your pillars do not cover?"
                ),
            )
        )
    return out


def from_harry(path: str | Path | None = None) -> list[Signal]:
    """Read Harry Hindsight's thesis ledger (``harry_theses.json``).

    Harry never edits a thesis file. When he reads one as BROKEN, it lands
    here as a question on that thesis, answered the same way as Sally's: a
    dated review with ``trigger: HARRY_BROKEN``.
    """
    data = _load_json(Path(path) if path else DASHBOARD_DIR / "harry_theses.json")
    out: list[Signal] = []
    for row in data.get("theses", []):
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker or row.get("thesis") != "BROKEN":
            continue
        breached = [pid for pid, st in (row.get("pillars") or {}).items() if st == "BREACHED"]
        bits = [str(row.get("severity", "")).strip(), str(row.get("verdict", "")).strip()]
        if breached:
            bits.append("breached: " + ", ".join(breached))
        if row.get("biases"):
            bits.append("biases: " + ", ".join(row["biases"]))
        out.append(
            Signal(
                source="Harry",
                ticker=ticker,
                kind=HARRY_BROKEN,
                detail=" · ".join(b for b in bits if b),
                date=_date(row.get("date")),
                question=(
                    "Harry reads this thesis as broken. Which pillar do you still "
                    "believe, what evidence says so, and what would make you sell?"
                ),
            )
        )
    return out


def from_bob_annual(path: str | Path | None = None) -> list[Signal]:
    """Read Bob's digest (``bob.json``) for full-year results on holdings.

    When Bob analyses a company's full-year result it lands on the dashboard as
    a results item (``type: results``, ``analysis.period_type: full_year``).
    That is the moment to update the thesis, so Theo turns it into an open
    question — the once-a-year refresh, keyed to each company's own reporting
    cycle because the result's arrival, not the calendar, is what fires it.

    Bob is never modified and does not know Theo exists; this only reads.
    """
    data = _load_json(Path(path) if path else DASHBOARD_DIR / "bob.json")
    when = _date(data.get("last_run"))
    out: list[Signal] = []
    seen: set[str] = set()
    for tier in ("high_impact", "material", "fyi"):
        for item in data.get(tier) or []:
            if item.get("type") != "results":
                continue
            analysis = item.get("analysis") or {}
            if str(analysis.get("period_type") or "").strip().lower() != "full_year":
                continue
            ticker = str(item.get("ticker", "")).strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            period = str(analysis.get("period") or "").strip()
            out.append(
                Signal(
                    source="Bob",
                    ticker=ticker,
                    kind=BOB_ANNUAL,
                    detail=f"{period} full-year result picked up".strip(),
                    date=when,
                    question=(
                        "Bob picked up the full-year result. Come in for the annual "
                        "refresh when you can — not mandatory, but it is the cheapest "
                        "honesty check there is: re-test each pillar against the new "
                        "numbers and update the hold thesis."
                    ),
                )
            )
    return out


def load_all(directory: str | Path | None = None) -> list[Signal]:
    """Every signal Theo currently knows how to read.

    Each source is one ``from_*`` reader over another agent's dashboard JSON;
    Theo never imports or calls those agents.
    """
    base = Path(directory) if directory else DASHBOARD_DIR
    return (
        from_sally(base / "sally.json")
        + from_harry(base / "harry_theses.json")
        + from_bob_annual(base / "bob.json")
    )


# --------------------------------------------------------------------------
# Matching signals to what was written down
# --------------------------------------------------------------------------


def answering_reviews(thesis: Thesis, signal: Signal) -> list:
    """Reviews that answer this signal — same trigger, on or after its date."""
    return [
        r
        for r in thesis.reviews
        if r.trigger == signal.kind
        and r.date is not None
        and (signal.date is None or r.date >= signal.date)
    ]


def is_answered(thesis: Thesis, signal: Signal) -> bool:
    return bool(answering_reviews(thesis, signal))


def open_questions(
    theses: Sequence[Thesis], signals: Sequence[Signal]
) -> list[tuple[Thesis, Signal]]:
    by_ticker = {t.ticker: t for t in theses}
    out = []
    for signal in signals:
        thesis = by_ticker.get(signal.ticker)
        if thesis is not None and not is_answered(thesis, signal):
            out.append((thesis, signal))
    return out


def orphans(theses: Sequence[Thesis], signals: Sequence[Signal]) -> list[Signal]:
    """Signals against tickers with no thesis at all — the worst case."""
    known = {t.ticker for t in theses}
    return [s for s in signals if s.ticker not in known]


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def findings_for(thesis: Thesis, signals: Iterable[Signal]) -> list[Finding]:
    """Drift findings this thesis earns from the other agents' signals."""
    out: list[Finding] = []
    mine = [s for s in signals if s.ticker == thesis.ticker]

    for signal in mine:
        if not is_answered(thesis, signal):
            out.append(
                Finding(
                    code="SIGNAL_UNANSWERED",
                    severity=WARN,
                    message=(
                        f"{signal.label} on {signal.date.isoformat() if signal.date else 'an unknown date'} "
                        "and nothing was written down either way"
                    ),
                    ticker=thesis.ticker,
                    detail=signal.detail,
                )
            )

    # Repeat refusals, counted per trigger across the whole file.
    by_trigger: dict[str, list] = {}
    for review in thesis.reviews:
        if review.trigger and review.decision == "DECLINED":
            by_trigger.setdefault(review.trigger, []).append(review)

    for trigger, reviews in by_trigger.items():
        if len(reviews) < REFUSAL_LIMIT:
            continue
        tightened = any(
            a.direction == "TIGHTENED" for r in reviews for a in r.amendments
        )
        if tightened:
            continue
        out.append(
            Finding(
                code="SIGNAL_REFUSED_REPEATEDLY",
                severity=ALERT,
                message=(
                    f"{trigger.replace('_', ' ').lower()} declined {len(reviews)} times "
                    "and no kill condition was ever tightened — the position is being "
                    "defended, not held"
                ),
                ticker=thesis.ticker,
                detail="; ".join(
                    f"{r.date.isoformat() if r.date else '?'}: {r.verdict}" for r in reviews
                ),
            )
        )

    return out


# --------------------------------------------------------------------------
# The answer block
# --------------------------------------------------------------------------


def answer_block(signal: Signal, today: dt.date | None = None) -> str:
    """A paste-ready ``reviews:`` entry.

    Theo prints this rather than editing the file itself. The thesis is your
    writing; a tool that rewrites your prose to add a field is a tool you stop
    trusting with your prose.
    """
    today = today or dt.date.today()
    return f"""  - date: {today.isoformat()}
    trigger: {signal.kind}
    decision: DECLINED        # ACTED | PARTIAL | DECLINED
    verdict: ""               # one line: what you decided
    expected_vs_actual: >-
      {signal.question}
    pillar_status: {{}}
    amendments: []
      # If declining means a pillar needs a real price-based kill condition,
      # write it here with direction: TIGHTENED. Declining three times with
      # no amendment is an alert.
"""
