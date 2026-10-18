"""Groups extracted claims into the durable per-trend dossier (brief
section 4) and keeps the causal chain from macro change through to
shareholder return traceable back to the claims that support it.

Claims are grouped deterministically by taxonomy category (code, not the
model) so a dossier is never created twice for the same category/name pair.
The narrative fields (thesis, duration, adoption curve, consequences,
invalidation criteria, ...) are synthesised by one structured Claude call
per dossier *update* -- not per claim -- so a reporting-season morning with
many new emails on the same trend costs one call, not one per email.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.llm import LLMResponse, describe_error, send

from .claim_extraction import _parse  # same JSON-repair discipline, reused rather than duplicated
from .config import RunConfig, TaxonomyCategory
from .schemas import ExtractedClaim, TrendDossier

SYSTEM_PROMPT = """\
You maintain a durable research dossier for one structural macro trend, \
for a long-horizon (5-20 year) equity investor. You are given the current \
dossier (if one exists) and a batch of new claims extracted from research \
emails, each tagged FACT/FORECAST/OPINION/INFERENCE with its own source.

Update the dossier fields below. Do not invent evidence: every factual \
statement you add must trace to one of the given claims (FACT/FORECAST/ \
OPINION only -- never upgrade an INFERENCE-tagged claim into a stated \
fact). Where the claims don't cover a field, leave it as it was (or empty \
if new). Distinguish a genuinely secular, multi-year trend from a cyclical \
rebound, a temporary shortage/price spike, or a speculative narrative --use \
"secular_or_cyclical" for that call, and say why in \
"what_changing_and_why" if it's a close call.

Reply with ONLY a JSON object, no prose, no markdown fences:
{
  "name": "short trend name",
  "thesis": "one paragraph",
  "what_changing_and_why": "...",
  "expected_duration": "e.g. '10-15 years, early-stage adoption'",
  "adoption_curve": "...",
  "demand_drivers": ["..."],
  "supply_constraints": ["..."],
  "capex_and_financing": "...",
  "policy_and_geopolitics": ["..."],
  "winners": ["..."],
  "losers": ["..."],
  "disrupted_business_models": ["..."],
  "first_order_consequences": ["..."],
  "second_order_consequences": ["..."],
  "third_order_consequences": ["..."],
  "evidence_for": ["..."],
  "evidence_against": ["..."],
  "invalidation_criteria": ["..."],
  "leading_indicators": ["..."],
  "secular_or_cyclical": "SECULAR" | "CYCLICAL_REBOUND" | "SPECULATIVE_NARRATIVE" | "UNDETERMINED",
  "confidence": "LOW" | "MEDIUM" | "HIGH"
}
"""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40]


def group_by_category(claims: list[ExtractedClaim]) -> dict[str, list[ExtractedClaim]]:
    out: dict[str, list[ExtractedClaim]] = {}
    for c in claims:
        for cat in c.taxonomy_categories or ["OTHER_EMERGING"]:
            out.setdefault(cat, []).append(c)
    return out


@dataclass
class DossierUpdate:
    status: str  # ok | failed | parse_error
    dossier: TrendDossier | None
    detail: str = ""


def dossier_id_for(category: TaxonomyCategory, claims: list[ExtractedClaim]) -> str:
    """Deterministic id so re-running never creates a duplicate dossier for
    the same category. v1 keeps one dossier per taxonomy category (the
    brief's categories are already trend-sized); a category that later
    needs splitting into several named trends is a scoring-time decision,
    not an ingestion-time one."""
    return f"dossier_{category.id.lower()}"


def synthesize_dossier(
    client,
    category: TaxonomyCategory,
    claims: list[ExtractedClaim],
    existing: TrendDossier | None,
    cfg: RunConfig,
) -> DossierUpdate:
    existing_json = existing.model_dump_json(indent=2) if existing else "(no existing dossier -- this is new)"
    claims_text = "\n\n".join(
        f"[{c.claim_type} | {c.confidence} | source: {c.source_name}] {c.text}\n"
        f"  companies={c.companies} industries={c.industries} commodities={c.commodities} "
        f"countries={c.countries} technologies={c.technologies} horizon={c.time_horizon}\n"
        f"  supporting: {c.supporting_evidence}\n  counter: {c.counter_evidence}"
        for c in claims
    )
    user = (
        f"Category: {category.label} ({category.id})\n\n"
        f"EXISTING DOSSIER:\n{existing_json}\n\n"
        f"NEW CLAIMS:\n{claims_text}"
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
        return DossierUpdate(status="failed", dossier=existing, detail=describe_error(exc))

    data = _parse(resp.text, resp.truncated)
    if data is None:
        detail = "truncated at max_tokens" if resp.truncated else "model reply was not valid JSON"
        return DossierUpdate(status="parse_error", dossier=existing, detail=detail)

    dossier_id = existing.id if existing else dossier_id_for(category, claims)
    source_refs = sorted({c.email_id for c in claims} | (set(existing.source_refs) if existing else set()))
    linked = sorted({co.upper() for c in claims for co in c.companies} | (set(existing.linked_companies) if existing else set()))
    dossier_kwargs = dict(
        id=dossier_id,
        category=category.id,
        name=data.get("name") or (existing.name if existing else category.label),
        thesis=data.get("thesis", existing.thesis if existing else ""),
        what_changing_and_why=data.get("what_changing_and_why", ""),
        expected_duration=data.get("expected_duration", ""),
        adoption_curve=data.get("adoption_curve", ""),
        demand_drivers=data.get("demand_drivers", []) or [],
        supply_constraints=data.get("supply_constraints", []) or [],
        capex_and_financing=data.get("capex_and_financing", ""),
        policy_and_geopolitics=data.get("policy_and_geopolitics", []) or [],
        winners=data.get("winners", []) or [],
        losers=data.get("losers", []) or [],
        disrupted_business_models=data.get("disrupted_business_models", []) or [],
        first_order_consequences=data.get("first_order_consequences", []) or [],
        second_order_consequences=data.get("second_order_consequences", []) or [],
        third_order_consequences=data.get("third_order_consequences", []) or [],
        evidence_for=data.get("evidence_for", []) or [],
        evidence_against=data.get("evidence_against", []) or [],
        invalidation_criteria=data.get("invalidation_criteria", []) or [],
        leading_indicators=data.get("leading_indicators", []) or [],
        linked_companies=linked,
        source_refs=source_refs,
        secular_or_cyclical=data.get("secular_or_cyclical", "UNDETERMINED"),
        confidence=data.get("confidence", "MEDIUM"),
    )
    if existing:
        dossier_kwargs["created_at"] = existing.created_at
    dossier = TrendDossier(**dossier_kwargs)
    return DossierUpdate(status="ok", dossier=dossier)
