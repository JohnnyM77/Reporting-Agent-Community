"""Company candidates: the macro -> company causal chain (brief section 7)
and the investment filter (section 8), for one ticker already named in the
dossier's claims.

Valuation numbers are never written by the model. ``resolve_valuation``
pulls real figures from ``shared/eodhd.py`` -- the repo's only market-data
source -- and anything EODHD doesn't have for that ticker renders
"not covered" / "n/a", never an estimate. The LLM call below is told this
explicitly and asked to reason about valuation qualitatively (expensive/
cheap relative to history and to the opportunity) without inventing a
number; the real multiples are attached afterwards, deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared import eodhd
from shared.llm import LLMResponse, describe_error, send

from .claim_extraction import _parse
from .config import RunConfig
from .schemas import (
    CompanyCandidate,
    ExtractedClaim,
    InvestmentFilter,
    TrendDossier,
    ValuationSnapshot,
)

SYSTEM_PROMPT = """\
You assess ONE candidate company as a possible beneficiary of ONE macro \
trend, for a long-horizon (5-20 year) equity investor whose philosophy is: \
identify structural change early, invest in the companies best positioned \
to benefit, buy at sensible valuations, and let the thesis compound.

You are told the trend dossier and the claims that named this company. You \
are NOT given live market data -- do not state a specific share price, \
P/E, EV/EBITDA or any other current multiple as fact; the caller attaches \
real sourced figures separately. Where you need to discuss valuation, \
reason qualitatively (e.g. "likely trades at a premium to history given \
consensus has caught up to this theme" or "undercovered, plausibly still \
cheap") and say explicitly that this is your own reasoning, not a sourced \
number.

Classify the company's exposure to the trend as exactly one of:
DIRECT_BENEFICIARY, BOTTLENECK_SUPPLIER, ENABLER, POTENTIAL_LOSER.

Build the causal chain from the macro change to a plausible shareholder \
return, as a short ordered list of one-line steps (MACRO CHANGE -> DEMAND \
CONSEQUENCE -> SUPPLY CONSTRAINT -> ECONOMIC BOTTLENECK -> INDUSTRY \
BENEFICIARIES -> COMPETITIVE ADVANTAGE -> COMPANY ECONOMICS -> CASH FLOW \
AND EARNINGS -> VALUATION -> POTENTIAL SHAREHOLDER RETURN -- skip a step \
only if it genuinely doesn't apply).

Fill the four-part investment filter as separate honest text, not a single \
buy/sell flag: a growing industry does not by itself make this company an \
attractive investment, and a high-quality company is not automatically a \
good purchase at any price -- say so if that's the situation here.

Reply with ONLY a JSON object, no prose, no markdown fences:
{
  "ticker": "the company's real exchange ticker, e.g. 'NVDA', 'BHP', 'TSM'",
  "exchange": "ASX" | "NYSE" | "NASDAQ" | "LSE" | "other exchange code",
  "currency": "AUD" | "USD" | "...",
  "name": "company name",
  "exposure_type": "DIRECT_BENEFICIARY" | "BOTTLENECK_SUPPLIER" | "ENABLER" | "POTENTIAL_LOSER",
  "causal_chain": ["MACRO CHANGE: ...", "DEMAND CONSEQUENCE: ...", "..."],
  "competitive_advantage": "...",
  "key_risks": ["..."],
  "why_now": "why this matters now, without trying to time a short-term move",
  "investment_filter": {
    "macro_attractiveness": "...",
    "industry_economics": "...",
    "company_quality": "...",
    "valuation_and_prospective_return": "... (qualitative only, see rules above)",
    "portfolio_suitability": "...",
    "further_work_needed": ["..."]
  }
}
"""


@dataclass
class CandidateResult:
    status: str  # ok | failed | parse_error
    candidate: CompanyCandidate | None
    detail: str = ""


def resolve_valuation(ticker: str, exchange_hint: str = "") -> ValuationSnapshot:
    """Real EODHD figures, or a clearly-labelled reason why there are none.
    Never raises -- a coverage gap is data, not a failure."""
    default_exchange = {"ASX": eodhd.ASX}.get((exchange_hint or "").upper(), eodhd.ASX)
    try:
        sym = eodhd.symbol(ticker, default_exchange=default_exchange)
    except eodhd.EODHDError as exc:
        return ValuationSnapshot(not_covered_reason=str(exc))
    try:
        snap = eodhd.snapshot(sym)
        price = None
        try:
            price = eodhd.price_summary(sym).last
        except Exception:  # noqa: BLE001 -- snapshot figures still stand without a fresh close
            pass
        return ValuationSnapshot(
            as_of=snap.updated_at or "",
            currency=snap.currency,
            price=price,
            pe=snap.trailing_pe,
            forward_pe=snap.forward_pe,
            ev_ebitda=snap.ev_to_ebitda,
            price_to_sales=snap.price_to_sales,
            dividend_yield_pct=(snap.dividend_yield * 100) if snap.dividend_yield is not None else None,
            fcf_yield_pct=(snap.fcf_yield * 100) if snap.fcf_yield is not None else None,
        )
    except eodhd.EODHDError as exc:
        return ValuationSnapshot(not_covered_reason=str(exc))


def build_candidate(
    client,
    company_name: str,
    dossier: TrendDossier,
    claims: list[ExtractedClaim],
    cfg: RunConfig,
) -> CandidateResult:
    """*company_name* is whatever the source claims named it (often a plain
    name, not a ticker) -- the model resolves the real ticker/exchange/
    currency; EODHD lookup below then stands or falls on that resolution."""
    claims_text = "\n".join(
        f"[{c.claim_type}] {c.text}" for c in claims if company_name.lower() in [co.lower() for co in c.companies]
    )
    user = (
        f"CANDIDATE COMPANY (as named in the source research): {company_name}\n\n"
        f"TREND DOSSIER: {dossier.name}\nThesis: {dossier.thesis}\n"
        f"Demand drivers: {dossier.demand_drivers}\nSupply constraints: {dossier.supply_constraints}\n"
        f"Winners named so far: {dossier.winners}\nLosers named so far: {dossier.losers}\n\n"
        f"CLAIMS NAMING THIS COMPANY:\n{claims_text or '(none directly -- inferred from the dossier context)'}"
    )
    try:
        resp: LLMResponse = send(
            client,
            model=cfg.model,
            max_tokens=cfg.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:  # noqa: BLE001
        return CandidateResult(status="failed", candidate=None, detail=describe_error(exc))

    data = _parse(resp.text, resp.truncated)
    if data is None:
        detail = "truncated at max_tokens" if resp.truncated else "model reply was not valid JSON"
        return CandidateResult(status="parse_error", candidate=None, detail=detail)

    exchange = str(data.get("exchange", "")).strip()
    ticker = str(data.get("ticker") or company_name).strip().upper()
    filt = data.get("investment_filter") or {}
    candidate = CompanyCandidate(
        dossier_id=dossier.id,
        ticker=ticker,
        exchange=exchange,
        currency=str(data.get("currency", "")),
        name=str(data.get("name", "")),
        exposure_type=data.get("exposure_type", "DIRECT_BENEFICIARY"),
        causal_chain=[str(s) for s in data.get("causal_chain", []) or []],
        competitive_advantage=str(data.get("competitive_advantage", "")),
        key_risks=[str(r) for r in data.get("key_risks", []) or []],
        why_now=str(data.get("why_now", "")),
        source_refs=sorted({c.email_id for c in claims}),
        is_asx=exchange.upper() == "ASX",
        investment_filter=InvestmentFilter(
            macro_attractiveness=str(filt.get("macro_attractiveness", "")),
            industry_economics=str(filt.get("industry_economics", "")),
            company_quality=str(filt.get("company_quality", "")),
            valuation_and_prospective_return=str(filt.get("valuation_and_prospective_return", "")),
            portfolio_suitability=str(filt.get("portfolio_suitability", "")),
            further_work_needed=[str(w) for w in filt.get("further_work_needed", []) or []],
        ),
        valuation=resolve_valuation(ticker, exchange),
    )
    return CandidateResult(status="ok", candidate=candidate)
