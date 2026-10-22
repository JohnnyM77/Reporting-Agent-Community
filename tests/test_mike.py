"""Mike (Mikebrisy's Stock Quality Assessment Framework v3.1): offline tests.
No network, no EODHD token, no API key, no SMTP."""

from __future__ import annotations

import json

import pytest

from mike import evidence as ev
from mike import qaqc, report
from mike.assess import ORDER, assess, classify
from mike.rubric import (balance_sheet, earnings_quality, earnings_stability, growth_track_record,
                         returns_on_capital)
from mike.series import annual_rows


def _fund(years: int = 11, *, rev0: float = 100e6, growth: float = 0.15, margin: float = 0.30,
          conv: float = 1.0, capex_pct: float = 0.02, debt: float = 0.0, cash: float = 50e6,
          shares0: float = 100e6, share_growth: float = 0.0, losses: tuple[int, ...] = (),
          interest: float = 0.0, issued: float = 0.0, eps_path: dict | None = None, start: int = 2016) -> dict:
    inc, bal, cfs = {}, {}, {}
    for i in range(years):
        d = f"{start + i}-06-30"
        rev = rev0 * (1 + growth) ** i
        ebit = rev * margin
        npat = -0.1 * rev if i in losses else ebit * 0.7
        if eps_path and i in eps_path:
            npat = eps_path[i]
        ebitda = ebit * 1.1
        cfo = ebitda * 0.85 * conv if npat > 0 else npat
        inc[d] = {"totalRevenue": str(rev), "ebit": str(ebit), "ebitda": str(ebitda), "incomeBeforeTax": str(npat / 0.7),
                  "incomeTaxExpense": str(npat / 0.7 * 0.3), "netIncome": str(npat), "interestExpense": str(interest)}
        cfs[d] = {"totalCashFromOperatingActivities": str(cfo), "capitalExpenditures": str(rev * capex_pct),
                  "issuanceOfCapitalStock": str(issued), "stockBasedCompensation": "0"}
        eq = 200e6 + i * 20e6
        bal[d] = {"totalStockholderEquity": str(eq), "shortLongTermDebtTotal": str(debt),
                  "cashAndShortTermInvestments": str(cash), "totalAssets": str(eq + debt + 100e6),
                  "totalCurrentLiabilities": "50000000", "goodWill": "0", "intangibleAssets": "0",
                  "commonStockSharesOutstanding": str(shares0 * (1 + share_growth) ** i)}
    return {"General": {"Code": "TST", "Name": "Test Co", "GicSector": "Information Technology"},
            "Financials": {"Income_Statement": {"currency_symbol": "AUD", "yearly": inc},
                           "Balance_Sheet": {"currency_symbol": "AUD", "yearly": bal},
                           "Cash_Flow": {"currency_symbol": "AUD", "yearly": cfs}}}


def _good_evidence(n_points: int = 4, overlays=None):
    tests = {}
    for i, k in enumerate(["leadership", "retention", "pricing", "barriers", "trajectory"]):
        tests[k] = ({"demonstrated": True, "evidence": f"Reported metric {i} rose every year FY21-FY25, 98% retention",
                     "period": "FY21-FY25", "source": "https://example.com/ar"} if i < n_points else {"demonstrated": False})

    def gather(name, code, sector, wp, log=print):
        return ev.EvidenceResult(ev.OK, {"market_tests": tests, "overlays": overlays or [],
                                         "challenges": {k: "challenge" for k in ORDER}})
    return gather


# --- rubric tables -----------------------------------------------------------

@pytest.mark.parametrize("drop,expected", [(0.05, 5), (0.15, 4), (0.30, 3), (0.50, 2), (0.70, 1)])
def test_stability_maps_max_decline_to_the_table(drop, expected):
    path = {i: 50e6 for i in range(11)}
    path[8] = 50e6 * (1 - drop)
    c = earnings_stability(annual_rows(_fund(eps_path=path)))
    assert c.base == expected


def test_stability_repeated_losses_score_zero():
    assert earnings_stability(annual_rows(_fund(losses=(7, 9)))).base == 0


@pytest.mark.parametrize("fcf_npat,cfo_ebitda,expected", [(1.05, 0.85, 5), (0.97, 0.75, 4), (0.85, 0.65, 3),
                                                            (0.75, 0.80, 3), (0.60, 0.80, 2), (0.40, 0.80, 1)])
def test_earnings_quality_bands(fcf_npat, cfo_ebitda, expected):
    from mike.series import YearRow
    rows = []
    for i in range(5):
        ebitda, npat = 100.0, 50.0
        cfo = ebitda * cfo_ebitda
        rows.append(YearRow(date=f"{2022 + i}-06-30", revenue=500.0, ebitda=ebitda, ebit=80.0, npat=npat,
                            cfo=cfo, capex=cfo - npat * fcf_npat, fcf=npat * fcf_npat, pbt=70.0, tax=20.0))
    c = earnings_quality(rows)
    assert c.base == expected, (c.metrics, c.base_reason)


def test_earnings_quality_reports_both_prescribed_ratios():
    c = earnings_quality(annual_rows(_fund()))
    assert c.calc("CFO / EBITDA (5y cumulative)").value is not None
    assert c.calc("FCF / NPAT (5y cumulative)").value is not None


def test_earnings_quality_withholds_ratio_on_negative_denominator():
    c = earnings_quality(annual_rows(_fund(losses=(6, 7, 8, 9, 10))))
    assert c.metrics["fcf_npat"] is None
    assert c.base in (0.0, 1.0)


def test_balance_net_cash_self_funded_is_five():
    assert balance_sheet(annual_rows(_fund(debt=0, cash=50e6)), []).base == 5


def test_balance_takes_the_lower_of_leverage_and_cover():
    rows = annual_rows(_fund(debt=300e6, cash=0, interest=40e6))
    c = balance_sheet(rows, [])
    from mike.rubric import _cover_band, _lev_band
    expected = min(_lev_band(c.metrics["nd_ebitda"])[0], _cover_band(c.metrics["interest_cover"])[0])
    assert c.base == expected


def test_balance_loss_maker_net_cash_cannot_score_high():
    rows = annual_rows(_fund(losses=(10,), cash=500e6))
    assert balance_sheet(rows, []).base <= 3


def test_balance_recurring_equity_raises_not_self_funding():
    rows = annual_rows(_fund(cash=50e6, issued=40e6))
    assert balance_sheet(rows, []).base <= 3


def test_returns_bands_against_wacc():
    c = returns_on_capital(annual_rows(_fund(margin=0.30)), 0.09)
    assert c.base >= 4
    low = returns_on_capital(annual_rows(_fund(margin=0.02)), 0.09)
    assert low.base <= 2


@pytest.mark.parametrize("g,expected", [(0.15, 5), (0.10, 4), (0.06, 3), (0.02, 2), (-0.03, 1)])
def test_growth_cagr_bands(g, expected):
    assert growth_track_record(annual_rows(_fund(growth=g))).base == expected


def test_growth_short_history_rule_caps_at_two():
    f = _fund(years=4, rev0=1e6, growth=1.5)
    assert growth_track_record(annual_rows(f)).base <= 2


# --- evidence: the model proposes, code decides -----------------------------

def test_market_point_needs_evidence_and_source():
    data = {"market_tests": {"leadership": {"demonstrated": True, "evidence": "short", "source": "x"},
                             "retention": {"demonstrated": True, "evidence": "Renewals of 97% every year FY21-FY25", "source": ""},
                             "pricing": {"demonstrated": True, "evidence": "Raised prices 5% a year FY21-FY25 with volumes up", "source": "AR"}}}
    rows = {r["key"]: r for r in ev.validate_tests(data)}
    assert not rows["leadership"]["awarded"] and not rows["retention"]["awarded"]
    assert rows["pricing"]["awarded"]


def test_forward_looking_evidence_cannot_raise():
    data = {"market_tests": {"barriers": {"demonstrated": True, "evidence": "Expected to win the pipeline of tenders over the TAM",
                                          "source": "deck"}},
            "overlays": [{"criterion": "growth", "adjustment": 0.5, "reason_code": "consistent_organic_growth",
                          "evidence": "Guidance implies 20% growth continuing", "source": "deck"}]}
    assert not {r["key"]: r for r in ev.validate_tests(data)}["barriers"]["awarded"]
    assert not ev.validate_overlays(data)[0]["accepted"]


def test_overlay_outside_permitted_list_rejected():
    data = {"overlays": [{"criterion": "balance", "adjustment": 0.5, "reason_code": "x",
                          "evidence": "Strong liquidity for many years now", "source": "AR"},
                         {"criterion": "quality", "adjustment": 0.5, "reason_code": "dilution",
                          "evidence": "Some reason here that is long enough", "source": "AR"}]}
    assert not any(o["accepted"] for o in ev.validate_overlays(data))


def test_anti_double_counting_rejects_reused_evidence():
    same = {"evidence": "Revenue rose in every one of the last ten years", "source": "AR"}
    data = {"overlays": [{"criterion": "growth", "adjustment": 0.5, "reason_code": "consistent_organic_growth", **same},
                         {"criterion": "stability", "adjustment": 0.5, "reason_code": "downturn_resilience", **same}]}
    out = ev.validate_overlays(data)
    assert out[0]["accepted"] and not out[1]["accepted"]


# --- assessment ---------------------------------------------------------------

def test_overall_is_unweighted_mean_of_six_and_market_equals_points():
    a = assess("TST", _fund(), gather=_good_evidence(4), archetypes={}, config={})
    finals = [a.criteria[k].final for k in ORDER]
    assert a.criteria["market"].final == 4
    assert a.overall == pytest.approx(round(sum(finals) / 6, 2))
    assert a.classification == classify(a.overall)


def test_overlays_capped_at_half_a_point():
    ovs = [{"criterion": "growth", "adjustment": 0.5, "reason_code": "consistent_organic_growth",
            "evidence": "Organic revenue up every year FY16-FY26 without acquisitions", "source": "AR"}]
    a = assess("TST", _fund(growth=0.10, share_growth=0.08), gather=_good_evidence(3, ovs), archetypes={}, config={})
    g = a.criteria["growth"]
    assert abs(g.final - g.base) <= 0.5


def test_no_evidence_means_market_unscored_and_draft():
    a = assess("TST", _fund(), use_evidence=False, archetypes={}, config={})
    a.render_ok, a.render_note = True, "ok"
    a.finalise()
    assert a.criteria["market"].final is None and a.provisional
    assert a.status == "DRAFT"


def test_full_evidence_and_render_passes():
    a = assess("TST", _fund(), gather=_good_evidence(3), archetypes={}, config={})
    a.render_ok, a.render_note = True, "ok"
    a.finalise()
    assert a.status == "PASS", a.draft_reasons


def test_material_and_extreme_risks_flagged():
    a = assess("TST", _fund(losses=(7, 8, 9, 10)), gather=_good_evidence(0), archetypes={}, config={})
    assert any("EXTREME" in r for r in a.risks)


def test_independent_recalculation_matches_workpaper():
    f = _fund()
    a = assess("TST", f, use_evidence=False, archetypes={}, config={})
    assert a.recalc["ok"], a.recalc


def test_classification_bands_match_v31():
    assert classify(0.9) == "Very Low" and classify(1.0) == "Low" and classify(2.5) == "Medium"
    assert classify(3.0) == "Medium-High" and classify(4.0) == "High"


def test_exact_mean():
    assert float(qaqc.exact_mean([5, 4.5, 3, 2, 4, 3.5])) == pytest.approx(22 / 6)


# --- output -------------------------------------------------------------------

def test_email_is_table_only_with_no_em_dashes():
    a = assess("TST", _fund(), gather=_good_evidence(3), archetypes={}, config={})
    a.render_ok = True
    a.finalise()
    import datetime as dt
    h = report.email_html([a], "Test", dt.datetime(2026, 10, 20), True)
    for banned in ("<style", "class=", "display:flex", "display:grid", "—"):
        assert banned not in h


def test_pdf_html_has_standard_scorecard_rows():
    a = assess("TST", _fund(), gather=_good_evidence(3), archetypes={}, config={})
    a.render_ok = True
    a.finalise()
    import datetime as dt
    h = report.build_pdf_html([a], "Test", dt.datetime(2026, 10, 20))
    for row in ("OVERALL QUALITY SCORE", "QUALITY TREND", "QA/QC STATUS", "Audit trail", "evidence register"):
        assert row in h


def test_run_from_cache_writes_outputs(tmp_path, monkeypatch):
    pytest.importorskip("weasyprint")
    pytest.importorskip("pypdf")
    from mike.main import run
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "TST.AU.json").write_text(json.dumps(_fund()), encoding="utf-8")
    res = run(["TST"], "Test", out_dir=tmp_path / "out", cache_dir=cache, gather=_good_evidence(3), log=lambda m: None)
    assert res["pdf_ok"] and (tmp_path / "out" / "mike_report.pdf").exists()
    assert res["assessments"][0].status == "PASS"


def test_portfolio_list_excludes_etfs():
    from mike.main import portfolio_tickers
    t = portfolio_tickers()
    assert t and not {"VAS", "VEU", "VHY"} & set(t)


def test_spend_limit_error_is_shortened():
    raw = ("BadRequestError (400): Error code: 400 - {'error': {'message': 'You have reached your specified API "
           "usage limits. You will regain access on 2026-11-01 at 00:00 UTC.'}}")
    assert ev.short_error(raw) == ("Anthropic API spend limit reached (resets 2026-11-01); "
                                   "raise it in the Claude Console")
