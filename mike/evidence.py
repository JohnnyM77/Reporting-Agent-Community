# mike/evidence.py
#
# The judgement half of the framework, kept on a short leash.
#
# One model call per company (web search on) builds:
#   * the Demonstrated Market Position evidence register (section 4.3): one
#     verdict per test, each tied to historical evidence and a source;
#   * qualitative overlays, only from each criterion's permitted list;
#   * the +/-0.5 adversarial challenge per criterion (section 8.4);
#   * candidate exceptional items, for a human to confirm (never applied).
#
# The model proposes, code decides (repo rule): a test without evidence and a
# source scores no point; forward-looking evidence (guidance, pipeline, TAM,
# backlog, targets) can never raise a score; an overlay outside the permitted
# list is rejected; overlays are capped at +/-0.5 per criterion in assess.py.
#
# Outcomes follow the repo's rule that a half-broken run never looks clean:
# OK, SKIPPED (no key / call cap), FAILED_API, FAILED_INVALID. Anything but OK
# leaves Market Position unscored and the assessment DRAFT.

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from mike.rubric import MARKET_TESTS

OK, SKIPPED, FAILED_API, FAILED_INVALID = "OK", "SKIPPED", "FAILED_API", "FAILED_INVALID"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 12000

# Section 4: the only qualitative overlays each criterion permits.
PERMITTED = {
    "stability": {
        "+": {"recurring_revenue": "Demonstrated recurring/contracted/repeat revenue",
              "diversification": "Broad diversification",
              "downturn_resilience": "Proven resilience in a downturn"},
        "-": {"concentration": "Customer/product concentration",
              "commodity_exposure": "Commodity exposure",
              "binary_events": "Binary events",
              "high_volatility": "Unusually high margin/revenue volatility"},
    },
    "quality": {
        "+": {"conservative_accounting": "Unusually conservative accounting and conversion quality not captured by the ratios"},
        "-": {"statutory_underlying_gaps": "Persistent statutory-versus-underlying gaps",
              "recurring_one_offs": "Recurring 'one-offs'",
              "aggressive_capitalisation": "Aggressive capitalisation",
              "poor_working_capital": "Poor working-capital quality"},
    },
    "growth": {
        "+": {"consistent_organic_growth": "Unusually consistent broad-based organic growth not captured by CAGR"},
        "-": {"acquisition_dependence": "Material acquisition dependence",
              "dilution": "Dilution",
              "one_off_growth_source": "Highly concentrated one-off growth source"},
    },
    "market": {
        "+": {"tests_understate": "The five tests materially understate the demonstrated position"},
        "-": {"tests_overstate": "The five tests materially overstate the demonstrated position"},
    },
}

FORWARD = re.compile(r"\b(guidance|pipeline|backlog|order book|TAM|addressable market|expect\w*|forecast\w*|"
                     r"target\w*|anticipat\w*|outlook|will (?:grow|win|expand|launch)|plans? to|potential)\b", re.I)

SYSTEM_PROMPT = """You assess DEMONSTRATED business quality under Mikebrisy's Stock Quality Assessment Framework v3.1.

Non-negotiable rules:
- Demonstrated evidence only: reported historical results or objectively verifiable operating evidence available today.
- No forward-looking uplift: guidance, backlog, pipeline, TAM, future launches, expected synergies, targets never count.
- Absence of evidence is not positive evidence. Missing evidence earns no point.
- A partnership, approval, IP or product advantage earns credit only to the extent it has ALREADY produced demonstrated retention, pricing, share, wins or barriers.
- Rising burden of proof: a point needs clear, specific, sourced evidence (numbers, dates, named reports).
- Anti-double-counting: each piece of evidence supports one criterion only.
- Statutory accounts first; treat recurring "one-offs" sceptically.

Use web search to find primary sources (annual reports, results presentations, ASX announcements, regulator or industry data).
Reply with ONE JSON object and nothing else."""


def build_prompt(company: str, ticker: str, sector: str, workpaper: str) -> str:
    tests = "\n".join(f'    "{k}": {{"demonstrated": true|false, "evidence": "specific historical evidence with numbers/dates", '
                      f'"period": "e.g. FY21-FY25", "source": "URL or document name"}},   // {label}: {rule}'
                      for k, label, rule in MARKET_TESTS)
    allowed = "\n".join(f"  {crit}: raise only for {', '.join(p['+'])}; lower only for {', '.join(p['-'])}"
                        for crit, p in PERMITTED.items() if crit != "market")
    return f"""Company: {company} ({ticker}). Sector: {sector}.

Quantitative workpaper already computed from EODHD statutory data (do not recompute or contradict these numbers):
{workpaper}

Return exactly this JSON:
{{
  "market_tests": {{
{tests}
  }},
  "market_overlay": {{"adjustment": 0, "reason_code": "tests_understate|tests_overstate|none", "evidence": "", "source": ""}},
  "overlays": [
    {{"criterion": "stability|quality|growth", "adjustment": 0.5 or -0.5, "reason_code": "<from the permitted list>",
      "evidence": "specific historical evidence", "source": "URL or document"}}
  ],
  "challenges": {{"stability": "", "quality": "", "market": "", "balance": "", "returns": "", "growth": ""}},
  "exceptional_items": [{{"fy": "FY25", "description": "e.g. impairment of X, A$Ym pre-tax", "source": ""}}],
  "sector_note": ""
}}

Permitted overlays (anything else is rejected; Balance Sheet and Returns have no qualitative overlay):
{allowed}

"challenges": for each criterion, the strongest evidence that the score implied by the workpaper is wrong by at least 0.5 points (either direction), in one or two sentences.
"exceptional_items": statutory items the company itself reported as one-off in the last five years, with source. Listing them does not change any score.
Only include an overlay when the evidence is specific and historical. Most companies need zero or one overlay."""


@dataclass
class EvidenceResult:
    status: str
    data: dict = field(default_factory=dict)
    error: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def short_error(text: str) -> str:
    """A card-sized reason. The API's spend-limit reply is a wall of JSON; say what it means."""
    t = str(text or "")
    m = re.search(r"usage limits\. You will regain access on ([0-9-]+)", t)
    if m:
        return f"Anthropic API spend limit reached (resets {m.group(1)}); raise it in the Claude Console"
    return t if len(t) <= 160 else t[:157] + "..."


def parse_json(text: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    dec, best = json.JSONDecoder(), None
    for m in re.finditer(r"\{", t):
        try:
            obj, _ = dec.raw_decode(t, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (best is None or len(json.dumps(obj)) > len(json.dumps(best))):
            best = obj
    if best is None:
        raise ValueError("no JSON object in the reply")
    return best


def gather(company: str, ticker: str, sector: str, workpaper: str, *,
           send: Optional[Callable[..., Any]] = None, make_client: Optional[Callable[[], Any]] = None,
           model: Optional[str] = None, max_tokens: Optional[int] = None, web_search: bool = True,
           log: Callable[[str], None] = print) -> EvidenceResult:
    from shared import llm

    send = send or llm.send
    model = model or os.environ.get("MIKE_MODEL") or DEFAULT_MODEL
    max_tokens = max_tokens or int(os.environ.get("MIKE_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
    res = EvidenceResult(status=FAILED_API)
    if make_client is None and not llm.get_api_key():
        res.status, res.error = SKIPPED, "ANTHROPIC_API_KEY not set"
        return res
    try:
        client = (make_client or llm.make_client)()
    except Exception as exc:  # noqa: BLE001
        res.error = llm.describe_error(exc)
        return res
    extra: dict = {}
    if web_search:
        extra["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]
    messages: list = [{"role": "user", "content": build_prompt(company, ticker, sector, workpaper)}]
    for attempt in range(2):
        try:
            resp = send(client, model=model, max_tokens=max_tokens, messages=messages, system=SYSTEM_PROMPT, **extra)
            res.calls += 1
            pauses = 0
            while getattr(resp, "stop_reason", None) == "pause_turn" and pauses < 3 and getattr(resp, "message", None) is not None:
                pauses += 1
                res.input_tokens += resp.input_tokens
                res.output_tokens += resp.output_tokens
                messages = messages + [{"role": "assistant", "content": resp.message.content}]
                resp = send(client, model=model, max_tokens=max_tokens, messages=messages, system=SYSTEM_PROMPT, **extra)
                res.calls += 1
        except Exception as exc:  # noqa: BLE001
            res.status, res.error = FAILED_API, short_error(llm.describe_error(exc))
            return res
        res.input_tokens += getattr(resp, "input_tokens", 0) or 0
        res.output_tokens += getattr(resp, "output_tokens", 0) or 0
        if getattr(resp, "truncated", False):
            res.status, res.error = FAILED_API, f"reply cut off at max_tokens={max_tokens}"
            return res
        try:
            data = parse_json(resp.text)
        except ValueError as exc:
            if attempt == 0:
                log(f"[mike] {ticker}: reply was not JSON ({exc}); asking once more")
                messages += [{"role": "assistant", "content": resp.text or "(empty)"},
                             {"role": "user", "content": "That was not a single valid JSON object. Return only the JSON object."}]
                continue
            res.status, res.error = FAILED_INVALID, f"reply was not valid JSON: {exc}"
            return res
        if not isinstance(data.get("market_tests"), dict):
            res.status, res.error = FAILED_INVALID, "reply had no market_tests register"
            return res
        res.status, res.data = OK, data
        return res
    return res


# ---------------------------------------------------------------------------
# Code decides: validate what the model proposed
# ---------------------------------------------------------------------------

def is_forward(text: str) -> bool:
    return bool(FORWARD.search(text or ""))


def validate_tests(data: dict) -> list[dict]:
    """One row per test: {key, label, awarded, evidence, period, source, rejected_because}."""
    raw = data.get("market_tests") or {}
    out = []
    for key, label, _ in MARKET_TESTS:
        t = raw.get(key) or {}
        ev, src = str(t.get("evidence") or "").strip(), str(t.get("source") or "").strip()
        claimed = bool(t.get("demonstrated"))
        why = ""
        if claimed and len(ev) < 25:
            why = "no specific evidence given"
        elif claimed and not src:
            why = "no source given"
        elif claimed and is_forward(ev) and not re.search(r"\d", ev):
            why = "forward-looking claim, not demonstrated"
        out.append({"key": key, "label": label, "awarded": claimed and not why, "claimed": claimed,
                    "evidence": ev, "period": str(t.get("period") or ""), "source": src, "rejected_because": why})
    return out


def validate_overlays(data: dict) -> list[dict]:
    """Model overlays checked against the permitted list and the forward rule."""
    rows = []
    mo = data.get("market_overlay") or {}
    items = list(data.get("overlays") or [])
    if mo and float(mo.get("adjustment") or 0) != 0:
        items.append({**mo, "criterion": "market"})
    seen: dict[str, str] = {}
    for o in items:
        crit = str(o.get("criterion") or "").strip().lower()
        try:
            adj = float(o.get("adjustment") or 0)
        except (TypeError, ValueError):
            adj = 0.0
        code = str(o.get("reason_code") or "").strip()
        ev, src = str(o.get("evidence") or "").strip(), str(o.get("source") or "").strip()
        why = ""
        if adj == 0:
            continue
        sign = "+" if adj > 0 else "-"
        allowed = (PERMITTED.get(crit) or {}).get(sign, {})
        if crit not in PERMITTED:
            why = f"no qualitative overlay is permitted on {crit or 'that criterion'}"
        elif code not in allowed:
            why = f"'{code}' is not a permitted {sign} overlay for {crit}"
        elif len(ev) < 25 or not src:
            why = "no specific sourced evidence"
        elif adj > 0 and is_forward(ev):
            why = "forward-looking evidence cannot raise a score"
        key = (ev[:80] + "|" + src).lower()
        if not why and key in seen and seen[key] != crit:
            why = f"same evidence already used for {seen[key]} (anti-double-counting)"
        if not why:
            seen[key] = crit
        rows.append({"criterion": crit, "adjustment": max(-0.5, min(0.5, adj)), "reason": allowed.get(code, code),
                     "evidence": ev, "source": src, "accepted": not why, "rejected_because": why})
    return rows
