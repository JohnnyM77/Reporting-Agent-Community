# mike/assess.py
#
# One company, end to end, in the framework's own order (section 9):
#   1. statutory history (EODHD) -> workpaper
#   2. quantitative base score per criterion
#   3. permitted overlays only, max +/-0.5 per criterion
#   4. anti-double-counting
#   5. unweighted arithmetic mean, recomputed independently
#   6. QA/QC; PASS or DRAFT
#   7. Quality Trend, separate from the score

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from mike import evidence as ev
from mike import qaqc
from mike.rubric import (MARKET_TESTS, Criterion, Overlay, balance_sheet, earnings_quality, earnings_stability,
                         growth_track_record, market_position_shell, pct, returns_on_capital)
from mike.series import YearRow, annual_rows, interim_cash_flows, statement_currency
from mike.trend import quality_trend

ROOT = Path(__file__).resolve().parent.parent
ORDER = ["stability", "quality", "market", "balance", "returns", "growth"]
CLASSES = [(4.0, "High"), (3.0, "Medium-High"), (2.0, "Medium"), (1.0, "Low"), (0.0, "Very Low")]


def classify(score: Optional[float]) -> str:
    if score is None:
        return "n/a"
    for floor, label in CLASSES:
        if score >= floor:
            return label
    return "Very Low"


def load_config(path: Path = ROOT / "config" / "mike.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_archetypes(path: Path = ROOT / "config" / "ticker_archetypes.yaml") -> dict[str, str]:
    if not path.exists():
        return {}
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("tickers") or {}
    return {str(k).upper().removesuffix(".AX"): v.get("archetype") for k, v in data.items()
            if isinstance(v, dict) and v.get("archetype")}


@dataclass
class Assessment:
    ticker: str
    name: str
    currency: Optional[str] = None
    sector: str = ""
    latest_fy: str = ""
    rows: list[YearRow] = field(default_factory=list)
    criteria: dict[str, Criterion] = field(default_factory=dict)
    market_register: list[dict] = field(default_factory=list)
    rejected_overlays: list[dict] = field(default_factory=list)
    exceptional_items: list[dict] = field(default_factory=list)
    challenges: dict = field(default_factory=dict)
    evidence_status: str = ""
    sector_note: str = ""
    overall: Optional[float] = None
    provisional: bool = False
    classification: str = "n/a"
    classification_ok: bool = True
    mean_ok: bool = True
    trend: str = "Stable"
    trend_notes: list[str] = field(default_factory=list)
    recalc: dict = field(default_factory=dict)
    render_ok: Optional[bool] = None
    render_note: str = "not yet rendered"
    certification: list[dict] = field(default_factory=list)
    status: str = "DRAFT"
    draft_reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    wacc: float = 0.09
    error: str = ""

    @property
    def weakest(self) -> Optional[Criterion]:
        scored = [c for c in self.criteria.values() if c.final is not None]
        return min(scored, key=lambda c: c.final) if scored else None

    def finalise(self) -> None:
        """Run the certification once the report has been rendered (8.7)."""
        if self.error:
            self.status, self.draft_reasons = "NOT SCORED", [self.error]
            return
        self.certification = qaqc.certify(self)
        fails = [f"{r['group']}: {r['check']}" + (f" ({r['note']})" if r["note"] else "")
                 for r in self.certification if r["status"] == "FAIL"]
        self.draft_reasons = fails
        self.status = "PASS" if not fails else "DRAFT"

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker, "name": self.name, "currency": self.currency, "sector": self.sector,
            "latest_fy": self.latest_fy, "overall": self.overall, "provisional": self.provisional,
            "classification": self.classification, "trend": self.trend, "trend_notes": self.trend_notes,
            "status": self.status, "draft_reasons": self.draft_reasons, "risks": self.risks,
            "criteria": {k: c.as_dict() for k, c in self.criteria.items()},
            "market_register": self.market_register, "rejected_overlays": self.rejected_overlays,
            "exceptional_items": self.exceptional_items, "challenges": self.challenges,
            "evidence_status": self.evidence_status, "certification": self.certification,
            "recalc": self.recalc, "wacc": self.wacc, "error": self.error,
        }


def workpaper_text(a: Assessment) -> str:
    lines = [f"Statutory figures, {a.currency}, financial years {a.rows[0].fy}-{a.rows[-1].fy}."]
    for r in a.rows[-6:]:
        lines.append(f"{r.fy}: revenue {r.revenue}, EBIT {r.ebit}, NPAT {r.npat}, CFO {r.cfo}, capex {r.capex}, "
                     f"net debt {r.net_debt}, shares {r.shares}")
    for k in ORDER:
        c = a.criteria[k]
        if k == "market":
            continue
        lines.append(f"{c.name}: base score {c.base} ({c.base_reason}); "
                     + "; ".join(f"{x.name} {x.display}" for x in c.calcs[:6]))
    return "\n".join(lines)


def _apply_overlays(c: Criterion, extra: list[Overlay]) -> None:
    c.overlays.extend(extra)
    if c.base is None:
        c.final = None
        return
    total = sum(o.adjustment for o in c.overlays if o.accepted)
    capped = max(-0.5, min(0.5, total))
    if capped != total:
        c.flags.append(f"Overlays totalled {total:+.1f}; capped at {capped:+.1f} (normal maximum +/-0.5)")
    c.final = max(0.0, min(5.0, round((c.base + capped) * 2) / 2))


def assess(ticker: str, fund: dict, *, config: Optional[dict] = None, archetypes: Optional[dict] = None,
           gather: Optional[Callable[..., ev.EvidenceResult]] = None, use_evidence: bool = True,
           log: Callable[[str], None] = print) -> Assessment:
    config = config if config is not None else load_config()
    code = ticker.upper().split(".")[0]
    g = fund.get("General") or {}
    a = Assessment(ticker=code, name=g.get("Name") or code, currency=statement_currency(fund),
                   sector=" / ".join(x for x in (g.get("GicSector"), g.get("GicIndustry")) if x))
    a.rows = annual_rows(fund)
    a.wacc = float(((config.get("wacc") or {}).get("by_ticker") or {}).get(code)
                   or (config.get("wacc") or {}).get("default") or 0.09)
    if len(a.rows) < 4:
        a.error = f"Only {len(a.rows)} financial year(s) on EODHD: the framework needs five"
        a.finalise()
        return a
    a.latest_fy = a.rows[-1].fy
    ccy = a.currency or ""
    arch = (archetypes if archetypes is not None else load_archetypes()).get(code)
    commodity = arch == "cyclical" or (g.get("GicSector") in ("Energy", "Materials"))

    a.criteria = {
        "stability": earnings_stability(a.rows, cyclical=commodity),
        "quality": earnings_quality(a.rows, ccy),
        "market": market_position_shell(a.rows),
        "balance": balance_sheet(a.rows, interim_cash_flows(fund), ccy),
        "returns": returns_on_capital(a.rows, a.wacc),
        "growth": growth_track_record(a.rows, ccy),
    }
    industry = (g.get("GicIndustry") or "") + " " + (g.get("Industry") or "")
    if any(w in industry for w in ("Insurance", "Banks", "Bank")):
        a.sector_note = ("Bank/insurer: EBITDA, net debt and ROIC are not the right lenses; the framework allows "
                         "sector-specific metrics, which Mike does not yet carry")

    # ---- evidence review (Market Position register + qualitative overlays)
    model_overlays: dict[str, list[Overlay]] = {k: [] for k in ORDER}
    mkt = a.criteria["market"]
    if use_evidence:
        res = (gather or ev.gather)(a.name, code, a.sector or "n/a", workpaper_text(a), log=log)
    else:
        res = ev.EvidenceResult(status=ev.SKIPPED, error="evidence review switched off for this run")
    a.evidence_status = res.status + (f": {res.error}" if res.error else "")
    if res.status == ev.OK:
        reg = ev.validate_tests(res.data)
        a.market_register = reg
        pts = sum(1 for t in reg if t["awarded"])
        mkt.base = float(pts)
        mkt.metrics["points"] = pts
        mkt.base_reason = f"{pts} of 5 evidence tests demonstrated"
        mkt.rationale = ", ".join(t["label"] for t in reg if t["awarded"]) or "No test objectively demonstrated"
        mkt.gates.append(qaqc_gate("Each awarded point tied to a defined test with evidence", True))
        for o in ev.validate_overlays(res.data):
            ov = Overlay(o["criterion"], o["adjustment"], o["reason"], o["evidence"], o["source"], "evidence-review",
                         o["accepted"], o["rejected_because"])
            if o["criterion"] in model_overlays:
                model_overlays[o["criterion"]].append(ov)
            if not o["accepted"]:
                a.rejected_overlays.append(o)
        a.challenges = res.data.get("challenges") or {}
        a.exceptional_items = [x for x in (res.data.get("exceptional_items") or []) if isinstance(x, dict)]
        if res.data.get("sector_note"):
            a.sector_note = a.sector_note or str(res.data.get("sector_note"))
    else:
        mkt.base = None
        mkt.base_reason = f"Evidence register not completed ({res.status})"
        mkt.rationale = "Not assessed: " + (res.error or res.status)
        mkt.gates.append(qaqc_gate("Each awarded point tied to a defined test with evidence", False, res.error or res.status))

    for o in (config.get("manual_overlays") or {}).get(code) or []:
        crit = str(o.get("criterion") or "")
        if crit in model_overlays:
            model_overlays[crit].append(Overlay(crit, max(-0.5, min(0.5, float(o.get("adjustment") or 0))),
                                                str(o.get("reason") or ""), str(o.get("evidence") or ""),
                                                str(o.get("source") or "config/mike.yaml"), "manual"))

    # QA guard 8.5: an uplift may not take Earnings Quality to >=4 with FCF/NPAT under 80%.
    q = a.criteria["quality"]
    fcf = q.metrics.get("fcf_npat")
    for o in model_overlays["quality"]:
        if o.accepted and o.adjustment > 0 and (q.base or 0) + 0.5 >= 4 and (fcf is None or fcf < 0.80):
            o.accepted, o.rejected_because = False, "would take Earnings Quality to >=4 with FCF/NPAT under 80% (8.5)"
            a.rejected_overlays.append({"criterion": "quality", "adjustment": o.adjustment, "reason": o.reason,
                                        "rejected_because": o.rejected_because})
    for k in ORDER:
        _apply_overlays(a.criteria[k], model_overlays[k])

    # ---- overall: unweighted mean of the six, recomputed exactly
    finals = [a.criteria[k].final for k in ORDER]
    have = [f for f in finals if f is not None]
    if have:
        a.provisional = len(have) < 6
        a.overall = round(sum(have) / len(have), 2)
        exact = qaqc.exact_mean(have)
        a.mean_ok = abs(float(exact) - a.overall) < 0.005 + 1e-9
        a.classification = classify(a.overall)
        a.classification_ok = classify(float(exact)) == a.classification or abs(float(exact) - a.overall) < 0.005
    for k in ORDER:
        c = a.criteria[k]
        if c.final is not None and c.final <= 1.0:
            a.risks.append(f"{c.name} {c.final:g}: {'EXTREME' if c.final == 0 else 'material'} quality risk")
        c.challenge = " ".join(x for x in (qaqc.band_test(k, c.metrics), str(a.challenges.get(k) or "")) if x)

    # ---- independent recalculation (8.4) and cross-foot (8.6)
    dates = [r.date for r in a.rows[-5:]]
    ind = qaqc.independent_ratios(fund, dates)
    ok = qaqc.reconcile(q.metrics.get("cfo_ebitda"), ind["cfo_ebitda"]) and qaqc.reconcile(q.metrics.get("fcf_npat"), ind["fcf_npat"])
    a.recalc = {
        "ok": ok,
        "note": f"CFO/EBITDA {pct(q.metrics.get('cfo_ebitda'), 1)} vs {pct(ind['cfo_ebitda'], 1)}; "
                f"FCF/NPAT {pct(fcf, 1)} vs {pct(ind['fcf_npat'], 1)} (workpaper vs independent)",
        "crossfoot": abs(sum(r.cfo or 0 for r in a.rows[-5:]) - ind["sum_cfo"]) < 1.0 or ind["years"] < 5,
        "crossfoot_note": f"{ind['years']} years summed; annual CFO cross-foots to the cumulative figure",
    }
    a.trend, a.trend_notes = quality_trend(a.rows)
    return a


def qaqc_gate(check: str, passed: bool, note: str = ""):
    from mike.rubric import Gate
    return Gate(check, passed, note)
