"""Keeps config/ticker_archetypes.yaml in step with watchlists/*.yaml.

``sync_archetypes()`` runs at the start of every Wally and Sally run and from
the ``Archetype sync`` workflow on any push to watchlists/**:

  * a ticker on a watchlist with no entry is auto-classified and written with
    ``status: auto``;
  * a ticker on no watchlist gets ``active: false`` (history kept);
  * an entry with ``status: confirmed`` is never changed beyond ``lists`` and
    ``active``. Everything else about it is the owner's call.

Network failures never break a run: a ticker EODHD cannot classify is written
as ``unclassified`` with confidence 0 and retried next time.
"""
from __future__ import annotations

import datetime as dt
import html
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import yaml

from shared import classifier

REPO = Path(__file__).resolve().parents[1]
WATCHLIST_DIR = REPO / "watchlists"
TICKERS_YAML = REPO / "tickers.yaml"
ENTRIES_PATH = REPO / "config" / "ticker_archetypes.yaml"
REFRESH_DAYS = 90          # an unconfirmed entry is re-classified after this long

_HEADER = (
    "# One entry per ticker across watchlists/*.yaml (plus portfolio holdings).\n"
    "# Maintained by shared/archetype_sync.py. Edit by hand to confirm or override:\n"
    "#   status: confirmed   -> the sync and the classifier never change this entry\n"
    "#   override_multiple + override_reason -> always wins over the rules\n"
    "#   structural_headwind: true -> subtracts 2x (regulation, fee cuts)\n"
    "# Rules: config/valuation_archetypes.yaml. Explained: docs/VALUATION_RULES.md\n"
)


def _norm(raw: object) -> str:
    return str(raw or "").strip().upper()


def _identity(ticker: str) -> str:
    from shared.securities import US, parse_security
    try:
        return parse_security(ticker, US).key
    except ValueError:
        return ticker


def watchlist_membership(watchlist_dir: Path = WATCHLIST_DIR,
                         tickers_yaml: Optional[Path] = TICKERS_YAML) -> dict[str, list[str]]:
    """ticker (as written in the watchlist) -> list names it is on. De-duplicated across spellings."""
    import contextlib
    import io

    from wally.watchlist_loader import load_watchlist

    spelling: dict[str, str] = {}
    lists: dict[str, list[str]] = {}

    def add(ticker: str, list_name: str) -> None:
        ident = _identity(ticker)
        key = spelling.setdefault(ident, ticker)
        names = lists.setdefault(key, [])
        if list_name not in names:
            names.append(list_name)

    for path in sorted(Path(watchlist_dir).glob("*.yaml")):
        with contextlib.redirect_stdout(io.StringIO()):
            wl = load_watchlist(path)
        for t in wl.tickers:
            add(_norm(t), wl.name)

    if tickers_yaml and Path(tickers_yaml).exists():
        data = yaml.safe_load(Path(tickers_yaml).read_text(encoding="utf-8")) or {}
        for code, name in (data.get("asx") or {}).items():
            if "ETF" not in str(name).upper():
                add(f"{_norm(code)}.AX", "Portfolio")
        for code in (data.get("lse") or {}):
            add(f"{_norm(code).rstrip('.')}.L", "Portfolio")
        for code in (data.get("us") or {}):
            add(_norm(code), "Portfolio")
    return lists


def load_entries(path: Path = ENTRIES_PATH) -> dict[str, dict]:
    if not Path(path).exists():
        return {}
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {str(k): dict(v or {}) for k, v in (data.get("tickers") or {}).items()}


def save_entries(entries: dict[str, dict], path: Path = ENTRIES_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"tickers": {k: entries[k] for k in sorted(entries)}},
                          sort_keys=False, allow_unicode=True, width=120)
    Path(path).write_text(_HEADER + body, encoding="utf-8")


def failed_classification(ticker: str, exc: object) -> classifier.Classification:
    return classifier.Classification(
        ticker=ticker, archetype=classifier.UNCLASSIFIED, suggested=True, confidence=0.0,
        reasons=[f"{type(exc).__name__}: {exc}"], base_multiple=None, modifiers=[],
        raw_multiple=None, buy_multiple=None, guardrails=[], median_pe_10y=None,
        eps_basis="none", eps_value=None, implied_buy_price=None, error=str(exc))


def _entry_from(cls: classifier.Classification, lists: list[str], today: str, prev: dict) -> dict:
    changed = prev.get("archetype") != cls.archetype
    return {
        "archetype": cls.archetype,
        "status": "auto",
        "override_multiple": prev.get("override_multiple"),
        "override_reason": prev.get("override_reason") or "",
        "structural_headwind": bool(prev.get("structural_headwind")),
        "lists": lists,
        "active": True,
        "last_classified": today,
        "company": (cls.features.company if cls.features else "") or prev.get("company", ""),
        "suggested_multiple": cls.buy_multiple,
        "confidence": cls.confidence,
        "emailed": False if (not prev or changed) else bool(prev.get("emailed")),
    }


def sync_archetypes(
    *,
    entries_path: Path = ENTRIES_PATH,
    membership: Optional[dict[str, list[str]]] = None,
    classify_fn: Optional[Callable[[str], classifier.Classification]] = None,
    today: Optional[dt.date] = None,
    results: Optional[dict[str, classifier.Classification]] = None,
    workers: int = 4,
    save: bool = True,
    log: Callable[[str], None] = lambda m: print(m, flush=True),
) -> dict:
    """Bring the entries file in step with the watchlists.

    Returns ``{"entries", "added", "deactivated", "reactivated", "reclassified"}``.
    ``results`` (optional dict) is filled with every Classification made, so a
    caller that needs them (the review workbook) doesn't fetch twice.
    """
    today_s = (today or dt.date.today()).isoformat()
    membership = membership if membership is not None else watchlist_membership()
    entries = load_entries(entries_path)
    rules = classifier.load_rules()
    classify_fn = classify_fn or (lambda t: classifier.classify_ticker(t, rules, entry=entries.get(t)))

    # Which tickers need a (re)classification: new, unclassified, or stale and unconfirmed.
    todo: list[str] = []
    for t in membership:
        e = entries.get(t)
        if e is None:
            todo.append(t)
        elif e.get("status") != "confirmed":
            age = None
            try:
                age = (dt.date.fromisoformat(today_s) - dt.date.fromisoformat(str(e.get("last_classified")))).days
            except (TypeError, ValueError):
                pass
            if e.get("archetype") == classifier.UNCLASSIFIED or age is None or age >= REFRESH_DAYS:
                todo.append(t)

    def run(t: str) -> classifier.Classification:
        try:
            return classify_fn(t)
        except Exception as exc:  # noqa: BLE001 - one bad ticker never kills a run
            return failed_classification(t, exc)

    added, reclassified = [], []
    if todo:
        log(f"[archetypes] classifying {len(todo)} ticker(s)")
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            done = list(pool.map(run, todo))
        for t, cls in zip(todo, done):
            if results is not None:
                results[t] = cls
            prev = entries.get(t, {})
            entries[t] = _entry_from(cls, membership[t], today_s, prev)
            (reclassified if prev else added).append(t)

    reactivated, deactivated = [], []
    for t, e in entries.items():
        if t in membership:
            e["lists"] = membership[t]
            if not e.get("active", True):
                e["active"] = True
                reactivated.append(t)
        elif e.get("active", True):
            e["active"] = False
            deactivated.append(t)

    if save and (todo or reactivated or deactivated or not Path(entries_path).exists()):
        save_entries(entries, entries_path)
    log(f"[archetypes] added={len(added)} reclassified={len(reclassified)} "
        f"deactivated={len(deactivated)} reactivated={len(reactivated)} total={len(entries)}")
    return {"entries": entries, "added": added, "deactivated": deactivated,
            "reactivated": reactivated, "reclassified": reclassified}


def safe_sync(**kw) -> Optional[dict]:
    """sync_archetypes for agent start-up: never raises."""
    try:
        return sync_archetypes(**kw)
    except Exception as e:  # noqa: BLE001
        print(f"[archetypes] sync failed (non-fatal): {type(e).__name__}: {e}", flush=True)
        return None


def pending_confirmation(entries: dict[str, dict]) -> list[tuple[str, dict]]:
    """Active auto entries not yet reported in an email."""
    return [(t, e) for t, e in sorted(entries.items())
            if e.get("active", True) and e.get("status") != "confirmed" and not e.get("emailed")]


def mark_emailed(tickers: list[str], path: Path = ENTRIES_PATH) -> None:
    entries = load_entries(path)
    for t in tickers:
        if t in entries:
            entries[t]["emailed"] = True
    save_entries(entries, path)


def new_tickers_html(pending: list[tuple[str, dict]]) -> str:
    """Table-only email block: 'New tickers needing confirmation'."""
    if not pending:
        return ""
    rules = classifier.load_rules()
    rows = []
    for t, e in pending:
        label = classifier.archetype_label(rules, e.get("archetype", ""))
        mult = e.get("suggested_multiple")
        rows.append(
            "<tr>"
            f"<td style='padding:3px 8px'>{html.escape(t)}</td>"
            f"<td style='padding:3px 8px'>{html.escape(str(e.get('company') or ''))}</td>"
            f"<td style='padding:3px 8px'>{html.escape(label)}</td>"
            f"<td style='padding:3px 8px'>{'n/a' if mult is None else f'{mult:g}x'}</td>"
            f"<td style='padding:3px 8px'>{float(e.get('confidence') or 0):.0%}</td>"
            f"<td style='padding:3px 8px'>{html.escape(', '.join(e.get('lists') or []))}</td>"
            "</tr>")
    return (
        "<h3 style='margin:16px 0 4px 0'>New tickers needing confirmation</h3>"
        "<p style='font-size:12px;color:#6b7280;margin:0 0 6px 0'>Auto-classified since the last run. "
        "Set <code>status: confirmed</code> (or an override) in config/ticker_archetypes.yaml.</p>"
        "<table style='border-collapse:collapse;font-size:12px' border='1' bordercolor='#d1d5db'>"
        "<tr style='background:#1F2D4E;color:white'><th>Ticker</th><th>Company</th><th>Suggested archetype</th>"
        "<th>Buy multiple</th><th>Confidence</th><th>Lists</th></tr>"
        + "".join(rows) + "</table>")
