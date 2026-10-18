"""shared/llm.py: the one Claude transport. Prompts/caps/parsing stay in agents."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace as NS
from unittest import mock

import pytest

from shared import llm


def _msg(text="hello", stop="end_turn", blocks=None, tin=10, tout=5):
    return NS(content=blocks if blocks is not None else [NS(type="text", text=text)],
              stop_reason=stop, usage=NS(input_tokens=tin, output_tokens=tout))


def _client(message):
    client = mock.MagicMock()
    client.messages.create.return_value = message
    stream_cm = mock.MagicMock()
    stream_cm.text_stream = iter([message.content[0].text if message.content else ""])
    stream_cm.get_final_message.return_value = message
    stream_cm.__enter__.return_value = stream_cm
    client.messages.stream.return_value = stream_cm
    return client


def test_short_call_uses_create_and_extracts_everything():
    client = _client(_msg("hi", tin=12, tout=3))
    r = llm.send(client, model="m", max_tokens=1000, system="sys", messages=[{"role": "user", "content": "x"}],
                 cache=False)
    assert (r.text, r.stop_reason, r.input_tokens, r.output_tokens, r.truncated) == ("hi", "end_turn", 12, 3, False)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs == {"model": "m", "max_tokens": 1000, "system": "sys", "messages": [{"role": "user", "content": "x"}]}
    client.messages.stream.assert_not_called()


def test_long_call_streams():
    client = _client(_msg("long", stop="max_tokens"))
    r = llm.send(client, model="m", max_tokens=llm.STREAMING_MIN_TOKENS, messages=[])
    assert r.text == "long" and r.truncated
    client.messages.create.assert_not_called()
    assert "system" not in client.messages.stream.call_args.kwargs


def test_extra_kwargs_pass_through():
    client = _client(_msg())
    llm.send(client, model="m", max_tokens=100, messages=[], thinking={"type": "adaptive"})
    assert client.messages.create.call_args.kwargs["thinking"] == {"type": "adaptive"}


def test_response_text_skips_thinking_and_joins_text_blocks():
    m = _msg(blocks=[NS(type="thinking", thinking="hmm"), NS(type="text", text="a"), NS(type="text", text="b")])
    assert llm.response_text(m) == "ab"


def test_response_text_untyped_blocks_use_first_text():
    assert llm.response_text(NS(content=[mock.MagicMock(text="first")])) == "first"
    assert llm.response_text(NS(content=[])) == ""


def test_make_client_requires_key_and_imports_lazily(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(llm.LLMConfigError):
        llm.make_client()
    fake = types.ModuleType("anthropic")
    fake.Anthropic = mock.MagicMock(return_value="client")
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", " k \n")
    assert llm.make_client() == "client"
    fake.Anthropic.assert_called_once_with(api_key="k")


def test_describe_error_includes_status():
    exc = RuntimeError("rate limited")
    exc.status_code = 429
    assert llm.describe_error(exc) == "RuntimeError (429): rate limited"
    assert llm.describe_error(ValueError("x")) == "ValueError: x"


def test_call_with_retry(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("once")
        return "ok"

    retried = []
    assert llm.call_with_retry(flaky, on_retry=lambda a, e: retried.append((a, str(e)))) == "ok"
    assert retried == [(1, "once")] and sleeps == [2.0]

    with pytest.raises(RuntimeError, match="always"):
        llm.call_with_retry(lambda: (_ for _ in ()).throw(RuntimeError("always")), max_retries=1)


def test_stream_can_be_forced_either_way():
    client = _client(_msg())
    llm.send(client, model="m", max_tokens=100_000, messages=[], stream=False)
    client.messages.stream.assert_not_called()
    llm.send(client, model="m", max_tokens=10, messages=[], stream=True)
    client.messages.stream.assert_called_once()


# --- prompt caching -------------------------------------------------------

def test_cache_marks_system_prompt_but_not_a_one_shot_document():
    client = _client(_msg())
    msgs = [{"role": "user", "content": [{"type": "document", "source": {}}, {"type": "text", "text": "q"}]}]
    llm.send(client, model="m", max_tokens=100, system="sys", messages=msgs, cache=True)
    kw = client.messages.create.call_args.kwargs
    assert kw["system"] == [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
    assert "extra_body" not in kw  # first turn: the PDF is never re-sent, so never pay to cache it
    assert "cache_control" not in str(kw["messages"])


def test_cache_marks_conversation_tail_on_a_continuation():
    client = _client(_msg())
    msgs = [{"role": "user", "content": "doc"}, {"role": "assistant", "content": "bad"},
            {"role": "user", "content": "fix it"}]
    llm.send(client, model="m", max_tokens=100, messages=msgs, cache=True)
    kw = client.messages.create.call_args.kwargs
    assert kw["extra_body"] == {"cache_control": {"type": "ephemeral"}}
    assert "system" not in kw


def test_cache_env_switch(monkeypatch):
    monkeypatch.setenv("LLM_PROMPT_CACHE", "0")
    client = _client(_msg())
    llm.send(client, model="m", max_tokens=100, system="sys", messages=[])
    assert client.messages.create.call_args.kwargs["system"] == "sys"
    monkeypatch.delenv("LLM_PROMPT_CACHE")
    assert llm.caching_enabled()


def test_cache_usage_is_reported():
    m = _msg(tin=50, tout=7)
    m.usage.cache_read_input_tokens = 1400
    m.usage.cache_creation_input_tokens = 0
    r = llm.send(_client(m), model="m", max_tokens=100, messages=[])
    assert (r.cache_read_tokens, r.cache_write_tokens) == (1400, 0)
    assert r.usage_line() == "in 50 / cached 1,400 / written 0 / out 7"


def test_cache_usage_defaults_to_zero_without_fields():
    r = llm.send(_client(_msg()), model="m", max_tokens=100, messages=[])
    assert (r.cache_read_tokens, r.cache_write_tokens) == (0, 0)


# --- Message Batches -------------------------------------------------------

def _batch_client(results, statuses=("in_progress", "ended")):
    """A client whose batch goes through *statuses*, then yields *results*.

    *results* maps custom_id -> Message (succeeded) or a result type string.
    """
    client = _client(_msg("direct"))
    seq = list(statuses)
    client.messages.batches.create.return_value = NS(id="msgbatch_1", processing_status=seq.pop(0))
    client.messages.batches.retrieve.side_effect = lambda _id: NS(processing_status=seq.pop(0) if seq else "ended")
    entries = []
    for cid, r in results.items():
        if isinstance(r, str):
            entries.append(NS(custom_id=cid, result=NS(type=r)))
        else:
            entries.append(NS(custom_id=cid, result=NS(type="succeeded", message=r)))
    client.messages.batches.results.return_value = iter(entries)
    return client


@pytest.fixture
def fast_batch(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(llm, "_clock", lambda: clock[0])
    monkeypatch.setattr(llm, "_sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(llm, "_batch_waited_s", 0.0)
    monkeypatch.delenv("LLM_BATCH_MAX_WAIT_MIN", raising=False)
    return clock


def test_batch_off_by_default(monkeypatch, fast_batch):
    monkeypatch.delenv("LLM_BATCH", raising=False)
    client = _client(_msg("hi"))
    assert llm.send(client, model="m", max_tokens=10, messages=[]).text == "hi"
    client.messages.batches.create.assert_not_called()


def test_batch_returns_the_batched_answer(monkeypatch, fast_batch):
    monkeypatch.setenv("LLM_BATCH", "1")
    client = _batch_client({"r0": _msg("from batch", tin=7, tout=2)})
    r = llm.send(client, model="m", max_tokens=10, system="sys", messages=[{"role": "user", "content": "x"}],
                 thinking={"type": "adaptive"})
    assert (r.text, r.input_tokens) == ("from batch", 7)
    client.messages.create.assert_not_called()
    params = client.messages.batches.create.call_args.kwargs["requests"][0]["params"]
    assert params["thinking"] == {"type": "adaptive"}
    assert params["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "stream" not in params and "streaming_min_tokens" not in params


def test_batch_continuation_puts_top_level_cache_in_params(fast_batch):
    client = _batch_client({"r0": _msg()})
    msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    llm.send(client, model="m", max_tokens=10, messages=msgs, batch=True)
    params = client.messages.batches.create.call_args.kwargs["requests"][0]["params"]
    assert params["cache_control"] == {"type": "ephemeral", "ttl": "1h"} and "extra_body" not in params


def test_send_many_keeps_order_and_resends_failures_direct(fast_batch):
    client = _batch_client({"r1": _msg("second"), "r0": "errored", "r2": "expired"})
    reqs = [dict(model="m", max_tokens=10, messages=[]) for _ in range(3)]
    out = llm.send_many(client, reqs, batch=True, log=lambda m: None)
    assert [o.text for o in out] == ["direct", "second", "direct"]
    assert client.messages.create.call_count == 2


def test_slow_batch_is_cancelled_and_sent_direct_within_the_cap(monkeypatch, fast_batch):
    monkeypatch.setenv("LLM_BATCH_MAX_WAIT_MIN", "1")
    client = _batch_client({}, statuses=["in_progress"] * 1000)
    r = llm.send(client, model="m", max_tokens=10, messages=[], batch=True)
    assert r.text == "direct"
    client.messages.batches.cancel.assert_called_once_with("msgbatch_1")
    assert fast_batch[0] <= 60
    # the budget is spent, so the next call skips the batch entirely
    client.messages.batches.create.reset_mock()
    llm.send(client, model="m", max_tokens=10, messages=[], batch=True)
    client.messages.batches.create.assert_not_called()


def test_batch_submit_failure_falls_back_direct(fast_batch):
    client = _client(_msg("direct"))
    client.messages.batches.create.side_effect = RuntimeError("batches unavailable")
    assert llm.send(client, model="m", max_tokens=10, messages=[], batch=True).text == "direct"


def test_batch_direct_fallback_error_still_raises(fast_batch):
    client = _batch_client({"r0": "errored"})
    client.messages.create.side_effect = ValueError("bad request")
    with pytest.raises(ValueError):
        llm.send(client, model="m", max_tokens=10, messages=[], batch=True)


def test_send_many_direct_when_off_captures_per_request_errors():
    client = _client(_msg("ok"))
    client.messages.create.side_effect = [_msg("ok"), RuntimeError("boom")]
    out = llm.send_many(client, [dict(model="m", max_tokens=1, messages=[])] * 2, batch=False)
    assert out[0].text == "ok" and isinstance(out[1], RuntimeError)
