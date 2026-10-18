"""Ned's news summaries: one batch for all hits, same cap and None-on-failure."""

from types import SimpleNamespace as NS

import pytest

from tests._stubs import stub_missing

stub_missing("feedparser", "yaml", "requests", "bs4")

ned_main = pytest.importorskip("ned.main")


def _hit(n):
    return {"tickers": ["BXB"], "source": "s", "title": f"t{n}", "description": "d"}


def test_summarise_all_respects_cap_and_failures(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(ned_main, "MAX_LLM_CALLS", 3)
    monkeypatch.setattr(ned_main, "make_client", lambda k: object())
    seen = {}

    def fake_many(client, reqs):
        seen["n"] = len(reqs)
        return [NS(text=" one "), RuntimeError("down")]

    monkeypatch.setattr(ned_main, "llm_send_many", fake_many)
    calls = [1]
    out = ned_main.llm_summarise_all([_hit(i) for i in range(5)], calls)
    assert seen["n"] == 2 and calls == [3]
    assert out == ["one", None, None, None, None]


def test_summarise_all_without_key_makes_no_call(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ned_main, "llm_send_many", lambda *a: pytest.fail("called"))
    assert ned_main.llm_summarise_all([_hit(0)], [0]) == [None]
