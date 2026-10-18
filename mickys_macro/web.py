"""Writes docs/data/mickys_macro.json -- the public-safe summary for the
dashboard. Raw email content, extracted claim text and full dossier detail
stay in the private store; only trend names/scores/rationale and company
candidate summaries (no dollar figures, no position sizes) go here.

Run through ``shared/public_safety.scrub_obj`` like every other agent's
public output, and still subject to ``scripts/leak_guard.py`` before any
Pages upload -- see CLAUDE.md's "Public safety" section.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from shared.public_safety import scrub_obj

from .schemas import CompanyCandidate, ProcessingLog, TrendDossier, TrendScore
from .store import Store

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "data" / "mickys_macro.json"


def _dossier_summary(d: TrendDossier, score: TrendScore | None) -> dict:
    out = {
        "name": d.name,
        "category": d.category,
        "thesis": d.thesis,
        "secular_or_cyclical": d.secular_or_cyclical,
        "confidence": d.confidence,
        "winners": d.winners[:5],
        "losers": d.losers[:5],
        "invalidation_criteria": d.invalidation_criteria[:3],
        "last_reviewed": d.last_reviewed,
    }
    if score:
        out["scorecard"] = {
            dim: {"score": getattr(score, dim).score, "rationale": getattr(score, dim).rationale}
            for dim in (
                "structural_demand_strength", "expected_duration", "supply_scarcity",
                "evidence_quality", "monetisation_visibility", "industry_economics",
                "investable_company_availability", "valuation_attractiveness",
                "portfolio_diversification", "consensus_crowding_risk",
            )
        }
    return out


def _candidate_summary(c: CompanyCandidate) -> dict:
    v = c.valuation
    return {
        "ticker": c.ticker,
        "exchange": c.exchange,
        "name": c.name,
        "exposure_type": c.exposure_type,
        "why_now": c.why_now,
        "dossier_id": c.dossier_id,
        "portfolio_overlap": c.portfolio_overlap,
        "valuation": {
            "currency": v.currency,
            "pe": v.pe,
            "forward_pe": v.forward_pe,
            "ev_ebitda": v.ev_ebitda,
            "dividend_yield_pct": v.dividend_yield_pct,
            "fcf_yield_pct": v.fcf_yield_pct,
            "not_covered_reason": v.not_covered_reason,
        },
        "last_reviewed": c.last_reviewed,
    }


def write_dashboard_json(store: Store, path: Path = OUTPUT_PATH) -> dict:
    dossiers = store.all("trend_dossier", TrendDossier)
    scores_by_dossier = {s.dossier_id: s for s in store.all("trend_score", TrendScore)}
    candidates = store.all("company_candidate", CompanyCandidate)
    logs = store.all("processing_log", ProcessingLog)
    failed = [l for l in logs if l.status.startswith("FAILED")]

    payload = {
        "last_run": dt.date.today().isoformat(),
        "dossier_count": len(dossiers),
        "candidate_count": len(candidates),
        "dossiers": [_dossier_summary(d, scores_by_dossier.get(d.id)) for d in dossiers],
        "candidates": [_candidate_summary(c) for c in candidates],
        "processing": {
            "total_logged": len(logs),
            "failed": len(failed),
            "failures": [{"status": l.status, "detail": l.detail} for l in failed[-10:]],
        },
    }
    safe = scrub_obj(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    return safe
