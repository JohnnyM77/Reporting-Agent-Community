import sys
import types

from src.alert_engine import AlertClassification, HARRY_TIER, apply_harry_flag, sally_verdict
from src.harry_flags import load_harry_flags


def test_flag_forces_a_review_when_sallys_screens_do_not_fire():
    quiet = AlertClassification(triggered=False, tier="none", reasons=[])
    out = apply_harry_flag(quiet, {"raised": "2026-09-23"})
    assert out.triggered and out.harry_flag and out.tier == HARRY_TIER
    assert "BROKEN" in out.reasons[-1] and "2026-09-23" in out.reasons[-1]
    assert sally_verdict(out) == "Sell review: Harry says thesis broken"


def test_flag_keeps_sallys_own_tier_when_her_screens_fire():
    fired = AlertClassification(triggered=True, tier="Tier 2: Review", reasons=["near high"])
    out = apply_harry_flag(fired, {"raised": "2026-09-23"})
    assert out.tier == "Tier 2: Review" and out.reasons[0] == "near high" and out.harry_flag


def test_no_flag_changes_nothing():
    fired = AlertClassification(triggered=True, tier="Tier 3: Deep Review", reasons=["x"])
    assert apply_harry_flag(fired, None) is fired
    assert sally_verdict(fired) == "Trim candidate"


def test_loader_reads_flags_and_tolerates_missing_or_bad_files(tmp_path):
    assert load_harry_flags(tmp_path) == {}
    (tmp_path / "data").mkdir()
    (tmp_path / "data/harry_flags.yaml").write_text(
        "updated: 2026-09-23\nflags:\n  ar9.ax:\n    raised: '2026-09-23'\n    verdict: Exit.\n")
    assert load_harry_flags(tmp_path) == {"AR9": {"raised": "2026-09-23", "verdict": "Exit."}}
    (tmp_path / "data/harry_flags.yaml").write_text("flags: [unclosed")
    assert load_harry_flags(tmp_path) == {}


def test_prompt_switches_to_a_sell_analysis_when_harry_flags(monkeypatch):
    from src import claude_analyst

    seen = {}

    def send(client, **kw):
        seen["prompt"] = kw["messages"][0]["content"]
        return types.SimpleNamespace(text="VERDICT: v\nRECOMMENDATION: Exit position")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setitem(sys.modules, "shared.llm", types.SimpleNamespace(make_client=lambda k: object(), send=send))
    out = claude_analyst.analyse_company("AR9", "archTIS", {"current_price": 0.1}, ["r"],
                                         harry_flag={"raised": "2026-09-23", "verdict": "Exit it."})
    assert "read the investment thesis for this holding as BROKEN" in seen["prompt"]
    assert "Exit it." in seen["prompt"] and "Hold / Trim position / Exit position" in seen["prompt"]
    assert out["recommendation"] == "Exit position"

    claude_analyst.analyse_company("NHC", "New Hope", {"current_price": 6.4}, ["near high"])
    assert "potentially over-valued" in seen["prompt"] and "Watch Only / Hold but stop adding" in seen["prompt"]
