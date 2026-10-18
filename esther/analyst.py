"""One model call per company, strict JSON back, one repair retry on a QC hard fail.

Outcomes follow Harry's rule that a half-broken run must never look clean:
OK, FAILED_API (no key, SDK error, truncation) or FAILED_INVALID (unparseable
or still failing hard QC after the repair). The caller renders each distinctly.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from esther import prompts
from esther.quality import DASHES, scrub_all

OK, FAILED_API, FAILED_INVALID, SKIPPED_CAP = "OK", "FAILED_API", "FAILED_INVALID", "SKIPPED_CAP"

DEFAULT_MODEL = "claude-opus-4-6"
DEFAULT_MAX_TOKENS = 16000

Log = Callable[[str], None]


@dataclass
class AnalystResult:
    status: str
    analysis: dict = field(default_factory=dict)
    error: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def parse_json(text: str) -> dict:
    """Strip fences, then take the outermost {...}. Raises ValueError if there isn't one."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # With web search on, the reply can open with "Let me check {...}" chatter
    # before the object. Take the largest object that decodes cleanly.
    dec = json.JSONDecoder()
    best: Optional[dict] = None
    for m in re.finditer(r"\{", t):
        try:
            obj, end = dec.raw_decode(t, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (best is None or len(json.dumps(obj)) > len(json.dumps(best))):
            best = obj
    if best is None:
        raise ValueError("no JSON object in the reply")
    return best


def clean(analysis: dict) -> dict:
    blob = json.dumps(analysis, ensure_ascii=False)
    n = sum(blob.count(d) for d in DASHES)
    out = scrub_all(analysis)
    out["_dashes_scrubbed"] = n
    return out


def analyse(
    user_prompt: str,
    *,
    content_blocks: Optional[list] = None,
    qc_errors_for: Callable[[dict], list[str]],
    send: Optional[Callable[..., Any]] = None,
    make_client: Optional[Callable[[], Any]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    web_search: bool = True,
    log: Log = print,
) -> AnalystResult:
    """Run the Esther call. *send*/*make_client* are injectable so tests stay offline."""
    from shared import llm

    send = send or llm.send
    model = model or os.environ.get("ESTHER_MODEL") or DEFAULT_MODEL
    max_tokens = max_tokens or int(os.environ.get("ESTHER_MAX_TOKENS") or DEFAULT_MAX_TOKENS)
    res = AnalystResult(status=FAILED_API)
    try:
        client = (make_client or llm.make_client)()
    except Exception as exc:
        res.error = llm.describe_error(exc)
        return res

    extra: dict = {}
    if web_search:
        extra["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}]

    first = list(content_blocks or []) + [{"type": "text", "text": user_prompt}]
    messages: list = [{"role": "user", "content": first}]

    for attempt in range(2):
        try:
            resp = send(client, model=model, max_tokens=max_tokens, messages=messages,
                        system=prompts.SYSTEM_PROMPT, **extra)
            res.calls += 1
            # A long web-search turn can pause; hand it back to carry on (bounded).
            pauses = 0
            while resp.stop_reason == "pause_turn" and pauses < 3 and resp.message is not None:
                pauses += 1
                res.input_tokens += resp.input_tokens
                res.output_tokens += resp.output_tokens
                messages = messages + [{"role": "assistant", "content": resp.message.content}]
                resp = send(client, model=model, max_tokens=max_tokens, messages=messages,
                            system=prompts.SYSTEM_PROMPT, **extra)
                res.calls += 1
        except Exception as exc:
            res.status, res.error = FAILED_API, llm.describe_error(exc)
            return res
        res.input_tokens += resp.input_tokens
        res.output_tokens += resp.output_tokens
        if resp.truncated:
            res.status, res.error = FAILED_API, f"reply cut off at max_tokens={max_tokens}"
            return res
        try:
            analysis = clean(parse_json(resp.text))
        except (ValueError, json.JSONDecodeError) as exc:
            if attempt == 0:
                log(f"[esther] reply was not valid JSON ({exc}); asking once more")
                messages += [{"role": "assistant", "content": resp.text or "(empty)"},
                             {"role": "user", "content": "That was not a single valid JSON object. Return only the JSON object."}]
                continue
            res.status, res.error = FAILED_INVALID, f"reply was not valid JSON: {exc}"
            return res

        errors = qc_errors_for(analysis)
        if errors and attempt == 0:
            log(f"[esther] {len(errors)} QC hard fail(s); one repair call")
            messages += [{"role": "assistant", "content": resp.text},
                         {"role": "user", "content": prompts.repair_prompt(errors)}]
            continue
        res.analysis = analysis
        if errors:
            res.status, res.error = FAILED_INVALID, "still failing QC after repair: " + "; ".join(errors)
        else:
            res.status = OK
        return res
    return res
