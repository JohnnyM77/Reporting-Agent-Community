"""Same-day Bob runs add to bob.json; a new day starts clean (MSV, 2026-10-19)."""

import datetime as dt
import json
import sys
import types
from pathlib import Path

from _stubs import stub_missing

stub_missing("anthropic", "playwright", "playwright.async_api", "googleapiclient",
             "googleapiclient.discovery", "googleapiclient.http",
             "google", "google.oauth2", "google.oauth2.credentials",
             "google.oauth2.service_account", "google.auth",
             "google.auth.transport", "google.auth.transport.requests")
_pw = types.ModuleType("playwright_fetch")
_pw.fetch_pdf_with_playwright = None  # type: ignore[attr-defined]
sys.modules.setdefault("playwright_fetch", _pw)
sys.path.insert(0, str(Path(__file__).parent.parent))

import agent  # noqa: E402

MSV = {"ticker": "MSV", "title": "Q1 FY27 update", "url": "u/msv", "type": "TRADING_UPDATE", "analysis": "a"}
FYI = {"ticker": "BXB", "title": "Notice", "url": "u/bxb"}


def _setup(tmp_path, monkeypatch, day="2026-10-19"):
    path = tmp_path / "bob.json"
    monkeypatch.setattr(agent, "BOB_DASHBOARD_JSON", path)
    monkeypatch.setattr(agent, "today_sgt_date", lambda: dt.date.fromisoformat(day))
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_quiet_rerun_keeps_the_mornings_items(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    agent._emit_bob_dashboard_json([MSV], [], [FYI], silence=False)
    agent._emit_bob_dashboard_json([], [], [], silence=True)
    d = _read(path)
    assert d["high_impact"] == [MSV] and d["fyi"] == [FYI]
    assert d["silence"] is False


def test_second_run_adds_new_items_and_dedupes(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    agent._emit_bob_dashboard_json([MSV], [], [FYI], silence=False)
    new = {"ticker": "NHC", "title": "Combine", "url": "u/nhc"}
    reanalysed = dict(MSV, analysis="b")
    agent._emit_bob_dashboard_json([new, reanalysed], [], [FYI], silence=False)
    d = _read(path)
    assert d["high_impact"] == [new, reanalysed]
    assert d["fyi"] == [FYI]


def test_item_keeps_its_highest_tier(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch)
    agent._emit_bob_dashboard_json([], [], [dict(MSV)], silence=False)
    agent._emit_bob_dashboard_json([MSV], [], [], silence=False)
    d = _read(path)
    assert d["high_impact"] == [MSV] and d["fyi"] == []


def test_new_day_starts_clean(tmp_path, monkeypatch):
    path = _setup(tmp_path, monkeypatch, "2026-10-18")
    agent._emit_bob_dashboard_json([MSV], [], [], silence=False)
    _setup(tmp_path, monkeypatch, "2026-10-19")
    agent._emit_bob_dashboard_json([], [], [], silence=True)
    d = _read(path)
    assert d["high_impact"] == [] and d["silence"] is True and d["last_run"] == "2026-10-19"
