"""Gather what JM's system already knows about one company.

Reads the other agents' published outputs and JM's own files. Never imports or
modifies those agents: if any file is missing or malformed Esther carries on
with less context and says so, the same contract Harry has.

Portfolio status is decided here, in code, from JM's real records, so the
model can never invent a holding (spec s.11 and s.14).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from shared.securities import strip_asx_suffix

REPO_ROOT = Path(__file__).resolve().parent.parent

OWNED, WATCHING, SOLD, NOT_TRACKED = "OWNED", "WATCHING", "SOLD / PREVIOUSLY OWNED", "NOT TRACKED"

# Per-agent cap on characters handed to the model, so one chatty agent can't crowd out the rest.
MAX_SECTION_CHARS = 6000


def norm(ticker: Any) -> str:
    return strip_asx_suffix(str(ticker or "")).strip().upper().rstrip(".")


@dataclass
class Portfolio:
    status: str
    detail: list[str] = field(default_factory=list)
    weight_pct: Optional[float] = None  # share of the book, percent; never dollars (public repo)

    @property
    def disclosure(self) -> str:
        return "Disc: I own shares." if self.status == OWNED else ""


@dataclass
class CompanyContext:
    ticker: str
    company: str
    portfolio: Portfolio
    sections: dict[str, str]
    missing: list[str]
    previous: Optional[dict] = None  # Esther's last run for this ticker

    def as_prompt(self) -> str:
        out = [f"# {self.ticker}: {self.company}", "",
               f"## Portfolio status (from JM's records, authoritative): {self.portfolio.status}"]
        out += [f"- {d}" for d in self.portfolio.detail]
        if self.previous:
            out += ["", "## Esther's previous run on this company (compare against it: what changed?)",
                    _clip(json.dumps(_previous_summary(self.previous), indent=1, default=str))]
        else:
            out += ["", "## Esther's previous run: none on record. Compare against JM's thesis and prior results instead."]
        for name, text in self.sections.items():
            out += ["", f"## {name}", text]
        if self.missing:
            out += ["", "## Not available this run", *[f"- {m}" for m in self.missing]]
        return "\n".join(out)


def _clip(text: str, limit: int = MAX_SECTION_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n...[clipped, {len(text) - limit} chars]"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_ticker_dicts(obj: Any, ticker: str, out: Optional[list] = None) -> list[dict]:
    """Every dict anywhere in *obj* whose ticker/symbol/code field names *ticker*."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for key in ("ticker", "symbol", "code", "asx_code"):
            if key in obj and norm(obj[key]) == ticker:
                out.append(obj)
                return out
        for v in obj.values():
            _find_ticker_dicts(v, ticker, out)
    elif isinstance(obj, list):
        for v in obj:
            _find_ticker_dicts(v, ticker, out)
    return out


def _thesis(root: Path, ticker: str) -> tuple[Optional[dict], str]:
    path = root / "theses" / f"{ticker}.md"
    if not path.exists():
        return None, ""
    text = path.read_text(encoding="utf-8")
    front: Optional[dict] = None
    if text.startswith("---"):
        try:
            _, fm, body = text.split("---", 2)
            front = yaml.safe_load(fm) or {}
            return front, body.strip()
        except Exception:
            pass
    return front, text


def _company_name(root: Path, ticker: str, thesis: Optional[dict]) -> str:
    if thesis and thesis.get("name"):
        return str(thesis["name"])
    try:
        data = yaml.safe_load((root / "tickers.yaml").read_text(encoding="utf-8")) or {}
        for section in data.values():
            if isinstance(section, dict):
                for k, v in section.items():
                    if norm(k) == ticker:
                        return str(v)
    except Exception:
        pass
    return ticker


def portfolio_status(root: Path, ticker: str, thesis: Optional[dict]) -> Portfolio:
    detail: list[str] = []
    status = NOT_TRACKED
    weight = None

    decisions = []
    try:
        decisions = [d for d in _read_json(root / "data" / "decisions.json").get("decisions", [])
                     if norm(d.get("ticker")) == ticker]
    except Exception:
        pass
    open_ = [d for d in decisions if str(d.get("status", "")).upper() == "OPEN"]
    if open_:
        status = OWNED
        weight = round(100 * sum(float(d.get("weight") or 0) for d in open_), 1) or None
        first = min(str(d.get("date")) for d in open_)
        detail.append(f"{len(open_)} open buy decision(s) in the ledger, first on {first}")
        prices = [d.get("price") for d in open_ if d.get("price")]
        if prices:
            detail.append("Buy prices in the ledger: " + ", ".join(f"${p}" for p in prices))
    elif decisions:
        status = SOLD
        detail.append(f"{len(decisions)} closed decision(s) in the ledger")

    if thesis:
        tstatus = str(thesis.get("status", "")).upper()
        detail.append(f"Thesis file status: {tstatus or 'n/a'}, archetype {thesis.get('archetype', 'n/a')}, "
                      f"conviction {thesis.get('conviction', 'n/a')}")
        if status == NOT_TRACKED and tstatus == "HELD":
            status = OWNED
        elif status == NOT_TRACKED and tstatus in ("SOLD", "EXITED", "CLOSED"):
            status = SOLD

    if status == NOT_TRACKED:
        for wl in sorted((root / "watchlists").glob("*.yaml")):
            try:
                if ticker in {norm(t) for t in _watchlist_tickers(yaml.safe_load(wl.read_text(encoding="utf-8")))}:
                    status = WATCHING
                    detail.append(f"On watchlist {wl.stem}")
                    break
            except Exception:
                continue
    if weight is not None:
        detail.append(f"Ledger capital weight at cost: about {weight}% (Harry's reports carry the current % of book)")
    return Portfolio(status=status, detail=detail, weight_pct=weight)


def _watchlist_tickers(data: Any) -> list[str]:
    out: list[str] = []
    if isinstance(data, dict):
        for key in ("tickers", "watchlist", "stocks", "items"):
            if key in data:
                out += _watchlist_tickers(data[key])
        if "targets" in data and isinstance(data["targets"], dict):
            out += list(data["targets"].keys())
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                out.append(str(item.get("ticker") or item.get("symbol") or ""))
    return out


def gather(ticker: str, root: Path = REPO_ROOT, previous: Optional[dict] = None,
           extra_sections: Optional[dict[str, str]] = None) -> CompanyContext:
    ticker = norm(ticker)
    sections: dict[str, str] = {}
    missing: list[str] = []

    thesis, body = _thesis(root, ticker)
    if thesis:
        sections["JM's thesis (theses/{}.md, owned by Theo)".format(ticker)] = _clip(
            yaml.safe_dump(thesis, sort_keys=False, allow_unicode=True, width=120) + "\n" + body, 12000)
    else:
        missing.append(f"No thesis file theses/{ticker}.md")

    val = root / "valuations" / f"{ticker.lower()}_ax.yaml"
    if val.exists():
        try:
            v = yaml.safe_load(val.read_text(encoding="utf-8")) or {}
            keep = {k: v.get(k) for k in ("business", "stock_type", "buy_multiple", "sell_multiple", "norm_eps", "earnings")}
            sections["JM's value-chart settings (valuations/)"] = _clip(yaml.safe_dump(keep, sort_keys=False))
        except Exception as exc:
            missing.append(f"valuations/{val.name} unreadable: {exc}")

    agents = (
        ("Harry Hindsight (Chief Sceptic) reports", "harry.json"),
        ("Harry's thesis ledger", "harry_theses.json"),
        ("Theo (thesis keeper)", "theo.json"),
        ("Selling Sally (weekly review)", "sally.json"),
        ("Wally the Watcher", "wally.json"),
        ("Bob the Bot (latest daily digest)", "bob.json"),
    )
    for label, fname in agents:
        path = root / "docs" / "data" / fname
        try:
            hits = _find_ticker_dicts(_read_json(path), ticker)
        except FileNotFoundError:
            missing.append(f"{label}: docs/data/{fname} not found")
            continue
        except Exception as exc:
            missing.append(f"{label}: unreadable ({exc})")
            continue
        if hits:
            sections[label] = _clip(json.dumps(hits, indent=1, default=str))
        else:
            missing.append(f"{label}: nothing on {ticker}")

    for name, text in (extra_sections or {}).items():
        sections[name] = _clip(text, 60000)

    return CompanyContext(
        ticker=ticker,
        company=_company_name(root, ticker, thesis),
        portfolio=portfolio_status(root, ticker, thesis),
        sections=sections,
        missing=missing,
        previous=previous,
    )


def _previous_summary(prev: dict) -> dict:
    a = prev.get("analysis", {})
    return {
        "date": prev.get("date"),
        "event": a.get("event"),
        "title": a.get("title"),
        "thesis_check": a.get("thesis_check"),
        "narrative_case": a.get("narrative_case") or a.get("scenarios"),
        "valuation": {k: (prev.get("valuation") or {}).get(k) for k in ("value", "weighted_value", "price", "upside")},
        "watching_next": a.get("watching_next"),
        "what_would_change_my_mind": a.get("what_would_change_my_mind"),
    }
