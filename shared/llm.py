# shared/llm.py
#
# One Claude transport for every agent. It owns the boring part of an
# Anthropic call: API key, client construction, streaming for long
# generations, pulling text / stop_reason / token usage out of the response,
# a readable error string, and a retry helper.
#
# It deliberately does NOT own prompts, model choice, call caps, JSON
# parsing or outcome sentinels. Those are each agent's decisions (Bob's
# LLM_SKIPPED/LLM_FAILED, Harry's OK/SKIPPED_CAP/FAILED_API/FAILED_INVALID
# and validation retry) and stay in the agent.
#
# ``anthropic`` is imported inside ``make_client`` so importing this module
# never requires the SDK, and a test that swaps ``sys.modules["anthropic"]``
# is honoured at call time.

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, TypeVar

# Anthropic's Python SDK refuses non-streaming ``messages.create`` calls whose
# expected duration exceeds ~10 minutes ("Streaming is required for
# operations that may take longer than 10 minutes"). Bob's 50k-token results
# budget hits that, so any call at or above this many output tokens goes
# through ``messages.stream``; below it the plain ``create`` path is used.
STREAMING_MIN_TOKENS = 8192

# Prompt caching (on by default; LLM_PROMPT_CACHE=0 turns it off).
#
# Two breakpoints, both free to place:
#   1. The system prompt. Every agent reuses the same system prompt across a
#      run (Bob's RESULTS_HYFY_PROMPT for every reporter that morning, the
#      SGX/US prompts, Harry's reviewer prompt), so the 2nd+ call inside
#      five minutes reads it at ~10% of the input price.
#   2. The conversation tail, only once a call is a continuation
#      (len(messages) > 1): Harry's and Esther's JSON-repair retry, Esther's
#      web-search pause_turn hand-backs. Those resend the whole PDF; with the
#      tail cached, the next hand-back reads it from cache.
#
# The first turn's PDF is deliberately NOT cached: a one-shot announcement is
# never sent again, and a cache write costs 1.25x, so caching it would raise
# the bill. Prompts below the model's minimum cacheable size (it varies
# by model) are simply not cached; no error, no charge.
_CACHE = {"type": "ephemeral"}


def caching_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    e = os.environ if env is None else env
    return (e.get("LLM_PROMPT_CACHE") or "1").strip().lower() not in ("0", "false", "no", "off")

T = TypeVar("T")


class LLMConfigError(RuntimeError):
    """ANTHROPIC_API_KEY is not set."""


def get_api_key(env: Optional[Mapping[str, str]] = None) -> str:
    """ANTHROPIC_API_KEY, stripped; "" when unset."""
    e = os.environ if env is None else env
    return (e.get("ANTHROPIC_API_KEY") or "").strip()


def make_client(api_key: Optional[str] = None) -> Any:
    """Build an ``anthropic.Anthropic`` client. Raises LLMConfigError without a key."""
    key = api_key if api_key is not None else get_api_key()
    if not key:
        raise LLMConfigError("ANTHROPIC_API_KEY is not set")
    import anthropic

    return anthropic.Anthropic(api_key=key)


@dataclass
class LLMResponse:
    text: str
    stop_reason: Optional[str]
    input_tokens: int
    output_tokens: int
    message: Any = None  # the SDK's final Message, for callers that need more
    cache_read_tokens: int = 0  # input served from cache (billed at ~10%)
    cache_write_tokens: int = 0  # input written to cache (billed at 1.25x)

    def usage_line(self) -> str:
        """``in 1,200 / cached 1,350 / written 0 / out 900`` for run logs."""
        return (f"in {self.input_tokens:,} / cached {self.cache_read_tokens:,} / "
                f"written {self.cache_write_tokens:,} / out {self.output_tokens:,}")

    @property
    def truncated(self) -> bool:
        """True when the model was cut off at max_tokens."""
        return self.stop_reason == "max_tokens"


def response_text(message: Any) -> str:
    """All text blocks of a Message joined, skipping thinking/tool blocks.

    Objects without typed blocks (test doubles, very old SDKs) fall back to
    the first block's ``.text``.
    """
    blocks = list(getattr(message, "content", None) or [])
    texts = [
        b.text for b in blocks
        if getattr(b, "type", None) == "text" and isinstance(getattr(b, "text", None), str)
    ]
    if texts:
        return "".join(texts)
    first = getattr(blocks[0], "text", None) if blocks else None
    return first if isinstance(first, str) else ""


def _usage(message: Any) -> tuple[int, int]:
    usage = getattr(message, "usage", None)
    out = []
    for field in ("input_tokens", "output_tokens"):
        try:
            out.append(int(getattr(usage, field, 0) or 0))
        except (TypeError, ValueError):
            out.append(0)
    return out[0], out[1]


def _cache_usage(message: Any) -> tuple[int, int]:
    usage = getattr(message, "usage", None)
    out = []
    for field in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        v = getattr(usage, field, 0)
        out.append(v if isinstance(v, int) else 0)
    return out[0], out[1]


def _with_cache(system: Optional[str], messages: list, kwargs: dict) -> None:
    """Add cache breakpoints to *kwargs* in place (see the note at the top)."""
    if isinstance(system, str) and system.strip():
        kwargs["system"] = [{"type": "text", "text": system, "cache_control": dict(_CACHE)}]
    if len(messages) > 1 and "cache_control" not in kwargs:
        # Automatic caching: the API puts the breakpoint on the last block.
        # Sent through extra_body so it works on any anthropic SDK version.
        body = dict(kwargs.get("extra_body") or {})
        body.setdefault("cache_control", dict(_CACHE))
        kwargs["extra_body"] = body


def send(
    client: Any,
    *,
    model: str,
    max_tokens: int,
    messages: list,
    system: Optional[str] = None,
    streaming_min_tokens: int = STREAMING_MIN_TOKENS,
    stream: Optional[bool] = None,
    cache: Optional[bool] = None,
    batch: Optional[bool] = None,
    **extra: Any,
) -> LLMResponse:
    """Make one Messages API call and return its text, stop reason and usage.

    Streams when ``max_tokens >= streaming_min_tokens``, unless *stream*
    forces it one way or the other. *extra* is passed
    straight through (e.g. Wally's ``thinking={"type": "adaptive"}``).
    Exceptions from the SDK propagate unchanged; retrying and turning them
    into a status is the caller's job (see ``call_with_retry``).

    *cache* adds prompt-cache breakpoints; None follows LLM_PROMPT_CACHE
    (default on). *batch* sends the call through the Message Batches API at
    half price; None follows LLM_BATCH (default off). See ``send_many``.
    """
    req = dict(model=model, max_tokens=max_tokens, messages=messages, system=system,
               streaming_min_tokens=streaming_min_tokens, stream=stream, cache=cache, **extra)
    if batching_enabled() if batch is None else batch:
        out = send_many(client, [req], batch=True)[0]
        if isinstance(out, BaseException):
            raise out
        return out
    return _direct(client, req)


def _prepare(req: Mapping[str, Any], *, ttl: Optional[str] = None) -> tuple[dict, bool]:
    """A send()-style request -> (Messages API kwargs, stream?)."""
    r = dict(req)
    system = r.pop("system", None)
    cache = r.pop("cache", None)
    stream = r.pop("stream", None)
    streaming_min = r.pop("streaming_min_tokens", STREAMING_MIN_TOKENS)
    kwargs: dict = r
    if system is not None:
        kwargs["system"] = system
    if caching_enabled() if cache is None else cache:
        _with_cache(system, kwargs["messages"], kwargs)
        if ttl:
            # Only touch the breakpoints _with_cache itself just created.
            if isinstance(system, str) and system.strip():
                kwargs["system"][-1]["cache_control"] = {**_CACHE, "ttl": ttl}
            body = kwargs.get("extra_body")
            if isinstance(body, dict) and body.get("cache_control") == _CACHE:
                body["cache_control"] = {**_CACHE, "ttl": ttl}
    if stream is None:
        stream = kwargs["max_tokens"] >= streaming_min
    return kwargs, bool(stream)


def _direct(client: Any, req: Mapping[str, Any]) -> LLMResponse:
    kwargs, stream = _prepare(req)
    if stream:
        # Streaming keeps the HTTP connection alive with periodic events, so
        # the SDK's non-streaming ceiling doesn't apply. get_final_message()
        # drains the stream and returns the same Message create() would have.
        with client.messages.stream(**kwargs) as s:
            message = s.get_final_message()
    else:
        message = client.messages.create(**kwargs)
    return _to_response(message)


def _to_response(message: Any) -> LLMResponse:
    stop = getattr(message, "stop_reason", None)
    tin, tout = _usage(message)
    cread, cwrite = _cache_usage(message)
    return LLMResponse(
        text=response_text(message) or "",
        stop_reason=str(stop) if stop else None,
        input_tokens=tin,
        output_tokens=tout,
        message=message,
        cache_read_tokens=cread,
        cache_write_tokens=cwrite,
    )


# --- Message Batches (half price, not instant) -----------------------------
#
# Off unless LLM_BATCH=1, which only the bots that don't need an instant
# answer set in their workflows (Wally, Sally, Harry, Ned's news scan), and
# only on scheduled runs: a manual dispatch goes direct.
#
# Never less functional than a direct call. Anything the batch doesn't
# return in time, or returns as errored/expired/canceled, is re-sent as a
# normal direct call, so the run still gets every answer and a hard API
# error still surfaces as the same exception the agent handles today. The
# waiting is capped per process (LLM_BATCH_MAX_WAIT_MIN, default 30) so a
# slow batch day costs at most that many Actions minutes; once it's spent,
# every later call in the run goes direct.

_batch_waited_s = 0.0
_sleep = time.sleep
_clock = time.monotonic


def batching_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    e = os.environ if env is None else env
    return (e.get("LLM_BATCH") or "").strip().lower() in ("1", "true", "yes", "on")


def _batch_budget_s() -> float:
    try:
        minutes = float(os.environ.get("LLM_BATCH_MAX_WAIT_MIN") or 30)
    except ValueError:
        minutes = 30.0
    return max(0.0, minutes * 60 - _batch_waited_s)


def _batch_params(kwargs: dict) -> dict:
    """Messages kwargs -> batch ``params`` (SDK-only extra_body merged in)."""
    params = {k: v for k, v in kwargs.items() if k not in ("extra_body", "extra_headers", "timeout")}
    params.update(kwargs.get("extra_body") or {})
    return params


def send_many(
    client: Any,
    requests: list,
    *,
    batch: Optional[bool] = None,
    log: Callable[[str], None] = print,
) -> list:
    """Run several independent send()-style requests; same order back.

    Each slot is an LLMResponse, or the exception its direct call raised
    (so one bad request never costs the others). With batching on, all of
    them go in one Message Batch; whatever doesn't come back as a success
    is re-sent directly.
    """
    global _batch_waited_s
    out: list = [None] * len(requests)
    todo = list(range(len(requests)))
    use_batch = (batching_enabled() if batch is None else batch) and bool(requests)
    budget = _batch_budget_s() if use_batch else 0.0
    if use_batch and budget <= 0:
        log("[llm/batch] wait budget for this run is spent; sending direct")
    elif use_batch:
        try:
            todo = _run_batch(client, requests, out, budget, log)
        except Exception as exc:  # submit/poll/read failed: fall back, never fail
            log(f"[llm/batch] batch path failed ({describe_error(exc)}); sending direct")
            todo = [i for i in range(len(requests)) if out[i] is None]
        if todo:
            log(f"[llm/batch] {len(todo)} of {len(requests)} not returned by the batch; sending direct")
    for i in todo:
        try:
            out[i] = _direct(client, requests[i])
        except Exception as exc:
            out[i] = exc
    return out


def _run_batch(client: Any, requests: list, out: list, budget_s: float, log) -> list:
    """Submit, wait (within *budget_s*), fill *out*; return indexes still to do."""
    global _batch_waited_s
    batch_reqs = [
        {"custom_id": f"r{i}", "params": _batch_params(_prepare(r, ttl="1h")[0])}
        for i, r in enumerate(requests)
    ]
    b = client.messages.batches.create(requests=batch_reqs)
    log(f"[llm/batch] submitted {b.id} ({len(batch_reqs)} request(s), wait cap {budget_s / 60:.0f} min)")
    try:
        poll = max(1.0, float(os.environ.get("LLM_BATCH_POLL_S") or 10))
    except ValueError:
        poll = 10.0
    started = _clock()
    status = getattr(b, "processing_status", None)
    try:
        while status != "ended":
            if _clock() - started >= budget_s:
                log(f"[llm/batch] {b.id} not finished after {budget_s / 60:.0f} min; cancelling")
                try:
                    client.messages.batches.cancel(b.id)
                except Exception:
                    pass
                return list(range(len(requests)))
            _sleep(min(poll, max(0.0, budget_s - (_clock() - started))))
            status = getattr(client.messages.batches.retrieve(b.id), "processing_status", None)
    finally:
        _batch_waited_s += _clock() - started
    log(f"[llm/batch] {b.id} ended after {_clock() - started:.0f}s")
    for entry in client.messages.batches.results(b.id):
        cid = str(getattr(entry, "custom_id", ""))
        result = getattr(entry, "result", None)
        if not cid.startswith("r") or not cid[1:].isdigit():
            continue
        i = int(cid[1:])
        if i < len(out) and getattr(result, "type", None) == "succeeded":
            out[i] = _to_response(result.message)
    return [i for i in range(len(requests)) if out[i] is None]


def describe_error(exc: BaseException) -> str:
    """``ClassName (status): message`` -- the real error, for logs and cards."""
    status = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}{f' ({status})' if status else ''}: {exc}"


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 1,
    delay_seconds: float = 2.0,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> T:
    """Call *fn*, retrying up to *max_retries* times on any exception.

    ``on_retry(attempt_number, exc)`` is called before each retry (attempt
    numbers start at 1). The last exception is re-raised when every attempt
    fails.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries:
                raise
            if on_retry:
                on_retry(attempt + 1, exc)
            time.sleep(delay_seconds)
    raise AssertionError("unreachable")  # pragma: no cover
