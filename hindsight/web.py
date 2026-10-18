"""Harry on the public website: docs/data/harry.json.

The site and the repo are public, so this writes a verdict-level summary per
report and nothing else by default: severity, verdict, thesis read, the fresh
capital and forced sale answers, what would change the call. The bias read
(Munger tendencies) is added when ``web.include_bias`` is set, and the position
when ``web.include_position`` is set, as percentages only (% vs cost, % of
book). No dollar amount and no average-cost price is ever written here.

The file keeps the newest ``web.max_entries`` reports, so a throwaway store on
the runner still gives the site a running history.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.public_safety import scrub_obj

from .render import clean

REL = Path("docs") / "data" / "harry.json"


def entry(b: dict, date: str, cfg: dict) -> dict[str, Any] | None:
    if b.get("status") != "OK":
        return None
    wcfg = cfg.get("web", {})
    out = b["output"]
    e: dict[str, Any] = {
        "date": date,
        "ticker": b.get("ticker") or "PORTFOLIO",
        "report_type": b["report_type"],
        "severity": out.severity,
        "verdict": clean(out.verdict),
        "severity_reason": clean(out.severity_reason),
        "thesis": out.thesis_test.classification if out.thesis_test else None,
        "would_buy_today": (out.fresh_capital_test.would_buy_today if out.fresh_capital_test else None),
        "would_rebuy": out.forced_sale_test.would_rebuy if out.forced_sale_test else None,
        "lollapalooza": bool(b.get("lolla") and b["lolla"].fired and out.severity == "LOLLAPALOOZA"),
        "what_would_change_my_mind": [clean(x) for x in out.what_would_change_my_mind[:5]],
        "unanswered_questions": [clean(x) for x in out.unanswered_questions[:5]],
        "disagreements": [{"with": d.with_agent, "point": clean(d.point)} for d in out.disagreements],
    }
    if wcfg.get("include_bias"):
        e["biases"] = [t.tendency for t in out.munger_scan if t.state in ("OBSERVED EVIDENCE", "CURRENTLY TRIGGERED")]
    if wcfg.get("include_position") and b.get("facts") is not None:
        e["position"] = _position_pcts(b["facts"])
    # Public file: no weights, and no position-sized money in the prose.
    return scrub_obj(e)


def _position_pcts(f: Any) -> dict[str, Any]:
    """Return vs cost only. No dollar amount, no average cost, and no weight:
    a weight plus any one dollar figure gives away the size of the portfolio."""
    return {
        "unrealised_pct": round(f.unrealised_pct, 1) if f.unrealised_pct is not None else None,
    }


LEDGER_REL = Path("docs") / "data" / "harry_theses.json"


def write_theses_ledger(repo_root: Path, reports: list[dict], date: str, holdings: set[str]) -> Path | None:
    """Harry's latest read of each holding's thesis, for Theo and the site.

    One row per holding, replaced whenever Harry reviews it again, so the file
    is always "where Harry stands on every thesis". Theo reads it
    (``theo.signals.from_harry``): a BROKEN read opens a question on that
    thesis until a dated review answers it. Percentages only, no dollars.
    """
    rows: dict[str, dict] = {}
    path = repo_root / LEDGER_REL
    try:
        rows = {r["ticker"]: r for r in json.loads(path.read_text(encoding="utf-8")).get("theses", [])}
    except (OSError, ValueError, KeyError, TypeError):
        rows = {}
    changed = False
    for b in reports:
        t = b.get("ticker")
        if b.get("status") != "OK" or not t or t not in holdings:
            continue
        out, tc = b["output"], b.get("tc")
        thesis = b.get("thesis_obj")
        model = out.thesis_test.classification if out.thesis_test else None
        detector = tc.classification if tc is not None else None
        rows[t] = {
            "ticker": t,
            "date": date,
            "thesis": "BROKEN" if "BROKEN" in (model, detector) else model,
            "harry_read": model,
            "detector_read": detector,
            "pillars": {p.id: p.status for p in thesis.pillars} if thesis is not None else {},
            "severity": out.severity,
            "verdict": clean(out.verdict),
            "biases": [x.tendency for x in out.munger_scan if x.state in ("OBSERVED EVIDENCE", "CURRENTLY TRIGGERED")],
            "would_buy_today": out.fresh_capital_test.would_buy_today if out.fresh_capital_test else None,
            "would_rebuy": out.forced_sale_test.would_rebuy if out.forced_sale_test else None,
            **(_position_pcts(b["facts"]) if b.get("facts") is not None else {}),
        }
        changed = True
    if not changed:
        return None
    order = {"BROKEN": 0, "WEAKENED": 1, "CHANGED": 2, "THESIS INTACT": 3, "STRENGTHENED": 4}
    ranked = sorted(rows.values(), key=lambda r: (order.get(r.get("thesis") or "", 5), r["ticker"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Older rows may predate the public-safety rules; scrub the whole file.
    path.write_text(json.dumps({"updated": date, "theses": scrub_obj(ranked)}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def write(repo_root: Path, reports: list[dict], date: str, cfg: dict) -> Path | None:
    wcfg = cfg.get("web", {})
    if not wcfg.get("publish", True):
        return None
    new = [e for e in (entry(b, date, cfg) for b in reports) if e]
    if not new:
        return None
    path = repo_root / REL
    try:
        existing = json.loads(path.read_text(encoding="utf-8")).get("reports", [])
    except (OSError, ValueError):
        existing = []
    keys = {(e["date"], e["ticker"], e["report_type"]) for e in new}
    kept = [e for e in existing if (e.get("date"), e.get("ticker"), e.get("report_type")) not in keys]
    reports_out = (new + kept)[: int(wcfg.get("max_entries", 20))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_run": date, "reports": scrub_obj(reports_out)}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path
