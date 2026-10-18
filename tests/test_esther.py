"""Esther the Wrestler: offline tests. No network, no API key, no SMTP."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from esther import analyst, context, main, quality, render, store
from esther.valuation import (BaseFigures, Scenario, ValuationInputError, implied_growth, run_valuation,
                              value_scenario)


NARR = Scenario("narrative case", 0.05, 0.15, 15, rationale="guidance")
STRESS = Scenario("stress case", 0.02, 0.10, 12, rationale="margin fails")


# --- valuation --------------------------------------------------------------

def test_scenario_matches_hand_calculation():
    b = BaseFigures(revenue_m=1000, shares_m=100, discount_rate=0.10, years=5)
    v = value_scenario(Scenario("x", 0.10, 0.20, 15), b)
    fut_rev = 1000 * 1.1 ** 5
    assert v.future_revenue_m == pytest.approx(fut_rev)
    assert v.future_value_per_share == pytest.approx(fut_rev * 0.20 * 15 / 100)
    assert v.value_today == pytest.approx(fut_rev * 0.20 * 15 / 100 / 1.1 ** 5)


def test_one_narrative_case_is_the_value_no_weighting():
    b = BaseFigures(revenue_m=1000, shares_m=100, report_currency="USD", price_currency="AUD",
                    fx_report_to_price=1.5, discount_rate=0.0, share_change_pa=-0.02)
    r = run_valuation(NARR, b, price=10.0, stress=STRESS)
    assert r.narrative.future_shares_m == pytest.approx(100 * 0.98 ** 5)
    assert r.value == pytest.approx(1000 * 1.05 ** 5 * 0.15 * 15 / (100 * 0.98 ** 5) * 1.5)
    assert r.upside == pytest.approx(r.value / 10 - 1)
    # the private stress case is reported but never pulls the published value down
    assert r.stress.value_today < r.value
    assert r.value == run_valuation(NARR, b, price=10.0).value
    assert not r.warnings


def test_implied_growth_round_trips():
    b = BaseFigures(revenue_m=500, shares_m=50, discount_rate=0.075)
    val = value_scenario(Scenario("x", 0.07, 0.12, 14), b).value_today
    assert implied_growth(val, 0.12, 14, b) == pytest.approx(0.07)


def test_stress_worth_more_than_narrative_warns():
    r = run_valuation(STRESS, BaseFigures(revenue_m=1000, shares_m=100), stress=NARR)
    assert any("stress case" in w for w in r.warnings)


def test_bad_inputs_raise():
    with pytest.raises(ValuationInputError):
        run_valuation(Scenario("x", 0.05, 0.15, 400), BaseFigures(revenue_m=1000, shares_m=100))
    with pytest.raises(ValuationInputError):
        run_valuation(NARR, BaseFigures(revenue_m=0, shares_m=100))


def test_dividends_are_a_separate_line():
    b = BaseFigures(revenue_m=1000, shares_m=100, dps=1.0, discount_rate=0.0, years=5)
    r = run_valuation(NARR, b, price=10)
    assert r.dividends_pv == pytest.approx(5.0)
    assert r.value_with_dividends == pytest.approx(r.value + 5.0)


def test_malformed_stress_case_never_blocks_the_published_case():
    a = _analysis(stress_case={"revenue_growth": "n/a"})
    narrative, stress = main.cases_from(a)
    assert stress is None and narrative.future_pe == 15


# --- quality ----------------------------------------------------------------

def test_scrub_dashes():
    assert quality.scrub_dashes("Revenue up — cash down") == "Revenue up, cash down"
    assert quality.scrub_dashes("FY25–FY27 and 2–4%") == "FY25-FY27 and 2-4%"
    assert "—" not in quality.scrub_dashes("a—b")


def test_banned_phrases_whole_words():
    assert quality.banned_found("Moreover, this underscores it") == ["moreover", "underscores"]
    assert quality.banned_found("Net debt leverage of 0.3x") == []


def _analysis(**over) -> dict:
    a = json.loads((Path(__file__).parent / "fixtures" / "esther_sample.json").read_text(encoding="utf-8"))
    a.update(over)
    return a


def test_sample_passes_hard_checks():
    assert main._qc_errors(_analysis()) == []


def test_word_limit_and_banned_are_hard_fails():
    long = " ".join(["word"] * 700)
    errs = quality.check(_analysis(narrative=long)).hard_errors
    assert any("500 words" in e for e in errs)
    errs = quality.check(_analysis(title="Furthermore, a delve")).hard_errors
    assert any("banned" in e.lower() for e in errs)


# --- analyst ----------------------------------------------------------------

def _resp(text, stop="end_turn"):
    return SimpleNamespace(text=text, stop_reason=stop, input_tokens=10, output_tokens=20, message=None,
                           truncated=stop == "max_tokens")


def test_parse_json_ignores_search_chatter():
    body = json.dumps({"a": 1, "b": {"c": 2}})
    assert analyst.parse_json("Let me check {the ASX}.\n" + body) == {"a": 1, "b": {"c": 2}}
    assert analyst.parse_json("```json\n" + body + "\n```") == {"a": 1, "b": {"c": 2}}


def test_analyse_repairs_once_then_ok():
    bad = _analysis(title="Moreover a title")
    good = _analysis()
    replies = iter([_resp(json.dumps(bad)), _resp(json.dumps(good))])
    res = analyst.analyse("p", qc_errors_for=main._qc_errors, send=lambda *a, **k: next(replies),
                          make_client=lambda: object(), web_search=False, log=lambda m: None)
    assert res.status == analyst.OK and res.calls == 2


def test_analyse_truncation_is_a_failure():
    res = analyst.analyse("p", qc_errors_for=main._qc_errors, send=lambda *a, **k: _resp("{", "max_tokens"),
                          make_client=lambda: object(), web_search=False, log=lambda m: None)
    assert res.status == analyst.FAILED_API and "max_tokens" in res.error


def test_analyse_without_key_fails_visibly():
    def boom():
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    res = analyst.analyse("p", qc_errors_for=main._qc_errors, make_client=boom, log=lambda m: None)
    assert res.status == analyst.FAILED_API and "ANTHROPIC_API_KEY" in res.error


# --- context / disclosure ---------------------------------------------------

def _mini_repo(tmp_path: Path) -> Path:
    (tmp_path / "theses").mkdir()
    (tmp_path / "theses" / "ABC.md").write_text("---\nticker: ABC\nname: Abc Ltd\nstatus: HELD\n---\nbody\n")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "decisions.json").write_text(json.dumps({"decisions": [
        {"ticker": "ABC", "date": "2024-01-01", "price": 1.0, "status": "OPEN", "weight": 0.05},
        {"ticker": "OLD", "date": "2020-01-01", "price": 2.0, "status": "CLOSED", "weight": 0.01}]}))
    (tmp_path / "watchlists").mkdir()
    (tmp_path / "watchlists" / "jm.yaml").write_text("tickers:\n  - WAT.AX\n")
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "docs" / "data" / "harry.json").write_text(json.dumps({"reports": [{"ticker": "ABC", "severity": "AMBER"}]}))
    return tmp_path


def test_portfolio_status_comes_from_records(tmp_path):
    root = _mini_repo(tmp_path)
    assert context.gather("ABC.AX", root=root).portfolio.status == context.OWNED
    assert context.gather("OLD", root=root).portfolio.status == context.SOLD
    assert context.gather("WAT", root=root).portfolio.status == context.WATCHING
    assert context.gather("ZZZ", root=root).portfolio.status == context.NOT_TRACKED
    ctx = context.gather("ABC", root=root)
    assert "Harry" in " ".join(ctx.sections) and ctx.company == "Abc Ltd"


def test_disclosure_only_for_real_holdings():
    rep = render.Report("ABC", "Abc", "OK", context.Portfolio(context.OWNED), analysis=_analysis())
    assert render.narrative_with_disclosure(rep)[1].endswith("Disc: I own shares.")
    rep = render.Report("ABC", "Abc", "OK", context.Portfolio(context.WATCHING), analysis=_analysis())
    assert "Disc:" not in render.narrative_with_disclosure(rep)[1]


# --- store ------------------------------------------------------------------

def test_store_refuses_a_tracked_path_in_the_public_repo(monkeypatch):
    monkeypatch.setenv("ESTHER_STORE_DIR", str(context.REPO_ROOT / "docs" / "esther_leak"))
    with pytest.raises(store.StoreConfigError):
        store.store_dir()


# --- end to end -------------------------------------------------------------

def test_run_from_saved_analysis_renders_email_and_markdown(tmp_path, monkeypatch):
    monkeypatch.setenv("ESTHER_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(main, "OUT_ROOT", tmp_path / "out")
    adir = tmp_path / "analyses"
    adir.mkdir()
    (adir / "NHC.json").write_text(json.dumps(_analysis()))
    reps = main.run(["NHC"], mode="full", analysis_dir=adir, send_email=False, use_market=False, log=lambda m: None)
    assert reps[0].status == analyst.OK, reps[0].error
    assert reps[0].valuation and reps[0].valuation.value > 0
    out = next((tmp_path / "out").iterdir())
    html_body = (out / "email.html").read_text(encoding="utf-8")
    md = (out / "NHC.md").read_text(encoding="utf-8")
    assert "SIMPLY WALL STREET INPUTS" in md and "MY VALUE" in md and "STRESS TEST (private" in md
    assert "Disc: I own shares." in md  # NHC is a real holding in this repo
    for banned in ("<style", "class=", "display:flex", "display:grid", "—"):
        assert banned not in html_body
    assert (tmp_path / "store" / "NHC" / "latest.json").exists()


def test_narrative_headings_are_not_swallowed_by_paragraphs():
    h = render._md_to_html("## What happened\nRevenue up.\n\n## So what?\nHold **firmly**.")
    assert h.count("<p ") == 2 and h.count("<div ") == 2 and "<b>firmly</b>" in h
    assert "What happened</div>" in h


def test_public_copy_must_not_talk_about_trimming_or_position_size():
    a = _analysis(narrative="## So what?\nIt's 11% of my portfolio so I'll trim some.")
    errs = main._qc_errors(a)
    assert any("private" in e for e in errs)
    assert quality.private_talk_found("Revenue up, margins steady. Watching 1H27.") == []
