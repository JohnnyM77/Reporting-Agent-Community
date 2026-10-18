"""Pydantic records for Micky's Macro. Same style as hindsight/schemas.py:
every record is a flat, JSON-serialisable model stored as one row of
JSON text (see store.py), never a database schema to migrate.

Claim type distinguishes the author's own claim from Micky's Macro's
inference, per the brief's traceability requirement: never present our own
inference as the source's claim.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

ClaimType = Literal["FACT", "FORECAST", "OPINION", "INFERENCE"]
ExposureType = Literal["DIRECT_BENEFICIARY", "BOTTLENECK_SUPPLIER", "ENABLER", "POTENTIAL_LOSER"]
ProcessingStatus = Literal["OK", "SKIPPED_CAP", "FAILED_API", "FAILED_INVALID"]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class EmailRecord(BaseModel):
    """One ingested email. Raw text stays in the private store only --
    never copied into docs/data/mickys_macro.json."""

    id: str = Field(default_factory=lambda: _id("email"))
    message_id: str  # Gmail/RFC822 Message-ID -- the dedup key
    thread_id: str = ""
    source_name: str  # priority_sources entry name, e.g. "Citrini Research"
    sender: str
    subject: str
    received_at: str  # ISO 8601
    gmail_link: str = ""
    article_links: list[str] = Field(default_factory=list)
    raw_text: str = ""
    created_at: str = Field(default_factory=_now)
    status: ProcessingStatus = "OK"
    status_detail: str = ""


class ExtractedClaim(BaseModel):
    """One claim/forecast/hypothesis pulled from a source, with the
    distinction the brief requires: the author's claim vs. our inference."""

    id: str = Field(default_factory=lambda: _id("claim"))
    email_id: str
    source_name: str
    claim_type: ClaimType
    text: str
    companies: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    commodities: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    time_horizon: str = ""
    supporting_evidence: str = ""
    counter_evidence: str = ""
    taxonomy_categories: list[str] = Field(default_factory=list)
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    created_at: str = Field(default_factory=_now)
    dossiered: bool = False  # set once this claim has contributed to a dossier synthesis
    # call -- a claim extracted this run but orphaned by the per-run call cap
    # must still get picked up by trend mapping on a later run, not silently
    # sit in the store forever uncounted (see 2026-10-18's first live run,
    # which spent its whole MAX_LLM_CALLS budget on claim extraction alone).


class TrendDossier(BaseModel):
    """The durable per-trend record (brief section 4). ``id`` is the
    taxonomy category id plus a short slug so re-running never creates a
    duplicate dossier for the same trend."""

    id: str
    category: str  # taxonomy category id
    name: str
    thesis: str = ""
    what_changing_and_why: str = ""
    expected_duration: str = ""
    adoption_curve: str = ""
    demand_drivers: list[str] = Field(default_factory=list)
    supply_constraints: list[str] = Field(default_factory=list)
    capex_and_financing: str = ""
    policy_and_geopolitics: list[str] = Field(default_factory=list)
    winners: list[str] = Field(default_factory=list)
    losers: list[str] = Field(default_factory=list)
    disrupted_business_models: list[str] = Field(default_factory=list)
    first_order_consequences: list[str] = Field(default_factory=list)
    second_order_consequences: list[str] = Field(default_factory=list)
    third_order_consequences: list[str] = Field(default_factory=list)
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    invalidation_criteria: list[str] = Field(default_factory=list)
    leading_indicators: list[str] = Field(default_factory=list)
    linked_companies: list[str] = Field(default_factory=list)  # tickers
    source_refs: list[str] = Field(default_factory=list)  # email/claim ids
    secular_or_cyclical: Literal["SECULAR", "CYCLICAL_REBOUND", "SPECULATIVE_NARRATIVE", "UNDETERMINED"] = (
        "UNDETERMINED"
    )
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    created_at: str = Field(default_factory=_now)
    last_reviewed: str = Field(default_factory=_now)


class ScoreDimension(BaseModel):
    score: int = Field(ge=1, le=10)
    rationale: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    uncertainty: str = ""


class TrendScore(BaseModel):
    """The ten-dimension scorecard (brief section 9). No combined score is
    ever computed here -- see scoring.py's docstring for why."""

    id: str = Field(default_factory=lambda: _id("score"))
    dossier_id: str
    structural_demand_strength: ScoreDimension
    expected_duration: ScoreDimension
    supply_scarcity: ScoreDimension
    evidence_quality: ScoreDimension
    monetisation_visibility: ScoreDimension
    industry_economics: ScoreDimension
    investable_company_availability: ScoreDimension
    valuation_attractiveness: ScoreDimension
    portfolio_diversification: ScoreDimension
    consensus_crowding_risk: ScoreDimension
    created_at: str = Field(default_factory=_now)


class ValuationSnapshot(BaseModel):
    """Real EODHD figures only -- any field EODHD doesn't have for this
    ticker is left None and rendered "n/a" / "not covered", never estimated."""

    as_of: str = ""
    currency: Optional[str] = None
    price: Optional[float] = None
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_ebitda: Optional[float] = None
    price_to_sales: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    fcf_yield_pct: Optional[float] = None
    not_covered_reason: str = ""


class InvestmentFilter(BaseModel):
    """Sections A-E of the brief's filter, kept as separate text fields on
    purpose: "attractive macro trend", "attractive industry", "attractive
    company" and "attractive investment at today's price" are four
    different conclusions and are never collapsed into one flag."""

    macro_attractiveness: str = ""
    industry_economics: str = ""
    company_quality: str = ""
    valuation_and_prospective_return: str = ""
    portfolio_suitability: str = ""
    further_work_needed: list[str] = Field(default_factory=list)


class CompanyCandidate(BaseModel):
    id: str = Field(default_factory=lambda: _id("co"))
    dossier_id: str
    ticker: str
    exchange: str = ""
    currency: str = ""
    name: str = ""
    exposure_type: ExposureType = "DIRECT_BENEFICIARY"
    causal_chain: list[str] = Field(default_factory=list)  # MACRO -> ... -> RETURN, one line each
    competitive_advantage: str = ""
    key_risks: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    valuation: ValuationSnapshot = Field(default_factory=ValuationSnapshot)
    investment_filter: InvestmentFilter = Field(default_factory=InvestmentFilter)
    portfolio_overlap: list[str] = Field(default_factory=list)  # e.g. "held", "on jm_watchlist"
    why_now: str = ""
    is_asx: bool = False
    created_at: str = Field(default_factory=_now)
    last_reviewed: str = Field(default_factory=_now)


class ProcessingLog(BaseModel):
    """One row per ingestion/extraction attempt, for retry/idempotency and
    the acceptance-criteria tests. Mirrors Harry's OK/SKIPPED_CAP/
    FAILED_API/FAILED_INVALID discipline: a half-broken run must never look
    like a clean one."""

    id: str = Field(default_factory=lambda: _id("log"))
    email_id: str
    status: ProcessingStatus
    detail: str = ""
    created_at: str = Field(default_factory=_now)
