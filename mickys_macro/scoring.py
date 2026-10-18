"""The ten-dimension scorecard from brief section 9.

Deliberately never combines the ten scores into one number. A single
"conviction score" would be exactly the "misleadingly precise probability
of success" the brief tells us not to build, and it would hide which
dimension is actually weak behind an average that looks fine. Every caller
(the weekly review, the dashboard) renders the vector, not a mean.

Scored by one structured Claude call per dossier, run on the weekly cadence
(not daily) since the scorecard should move only when the evidence base
has genuinely changed, not every morning.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.llm import LLMResponse, describe_error, send

from .claim_extraction import _parse
from .config import RunConfig
from .schemas import ScoreDimension, TrendDossier, TrendScore

DIMENSIONS = (
    "structural_demand_strength",
    "expected_duration",
    "supply_scarcity",
    "evidence_quality",
    "monetisation_visibility",
    "industry_economics",
    "investable_company_availability",
    "valuation_attractiveness",
    "portfolio_diversification",
    "consensus_crowding_risk",
)

SYSTEM_PROMPT = """\
You score one macro trend dossier across ten independent dimensions, \
1 (weak) to 10 (strong), for a long-horizon (5-20 year) equity investor. \
Score each dimension on its own evidence -- do not let a high score on one \
dimension pull up another. Give a one-sentence rationale, cite which \
pieces of evidence in the dossier you relied on, and name the biggest \
uncertainty for each score. Do NOT compute or suggest any combined/overall \
score -- that is deliberately not part of this task.

The ten dimensions:
  - structural_demand_strength: how strong and structural (not cyclical) is the demand driver?
  - expected_duration: how many years is this trend likely to run?
  - supply_scarcity: how real and durable is the supply constraint/bottleneck?
  - evidence_quality: how good is the evidence base (primary sources, corroboration) vs. narrative/hearsay?
  - monetisation_visibility: how clearly does the trend translate into revenue/earnings for identifiable companies?
  - industry_economics: how attractive is the industry structure (pricing power, returns on capital, barriers to entry)?
  - investable_company_availability: are there real, liquid, analysable public companies with genuine exposure?
  - valuation_attractiveness: at today's prices, how much of the opportunity is already priced in?
  - portfolio_diversification: would exposure here diversify or concentrate the existing portfolio?
  - consensus_crowding_risk: how consensus/crowded is this trade already (10 = genuinely contrarian/underfollowed, 1 = everyone's in it)?

Reply with ONLY a JSON object, no prose, no markdown fences:
{
  "<dimension_id>": {"score": 1-10, "rationale": "...", "evidence_refs": ["..."], "uncertainty": "..."},
  ... one entry per dimension listed above, same keys ...
}
"""


@dataclass
class ScoringResult:
    status: str  # ok | failed | parse_error
    score: TrendScore | None
    detail: str = ""


def score_dossier(client, dossier: TrendDossier, cfg: RunConfig) -> ScoringResult:
    user = (
        f"DOSSIER: {dossier.name} ({dossier.category})\n\n"
        f"Thesis: {dossier.thesis}\n"
        f"What's changing and why: {dossier.what_changing_and_why}\n"
        f"Expected duration: {dossier.expected_duration}\n"
        f"Adoption curve: {dossier.adoption_curve}\n"
        f"Secular or cyclical: {dossier.secular_or_cyclical}\n"
        f"Demand drivers: {dossier.demand_drivers}\n"
        f"Supply constraints: {dossier.supply_constraints}\n"
        f"Capex/financing: {dossier.capex_and_financing}\n"
        f"Winners: {dossier.winners}\nLosers: {dossier.losers}\n"
        f"Evidence for: {dossier.evidence_for}\nEvidence against: {dossier.evidence_against}\n"
        f"Invalidation criteria: {dossier.invalidation_criteria}\n"
        f"Linked companies so far: {dossier.linked_companies}\n"
        f"Dossier confidence: {dossier.confidence}"
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
        return ScoringResult(status="failed", score=None, detail=describe_error(exc))

    data = _parse(resp.text, resp.truncated)
    if data is None:
        detail = "truncated at max_tokens" if resp.truncated else "model reply was not valid JSON"
        return ScoringResult(status="parse_error", score=None, detail=detail)

    try:
        dims = {}
        for d in DIMENSIONS:
            raw = data.get(d) or {}
            dims[d] = ScoreDimension(
                score=int(raw.get("score", 5)),
                rationale=str(raw.get("rationale", "")),
                evidence_refs=[str(e) for e in raw.get("evidence_refs", []) or []],
                uncertainty=str(raw.get("uncertainty", "")),
            )
        score = TrendScore(dossier_id=dossier.id, **dims)
    except Exception as exc:  # noqa: BLE001
        return ScoringResult(status="parse_error", score=None, detail=f"malformed scorecard: {exc}")
    return ScoringResult(status="ok", score=score)
