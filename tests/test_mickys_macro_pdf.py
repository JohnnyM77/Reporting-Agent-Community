"""PDF generation tests for Micky's Macro. Skips cleanly if weasyprint
isn't installed in the test environment, same tolerance Harry's PDF tests
show (``tests/_stubs.py``-style: real library if present, no fake stub)."""

from __future__ import annotations

import importlib.util

import pytest

from mickys_macro import main as mm_main
from mickys_macro import pdf_render, reports
from mickys_macro.schemas import CompanyCandidate, TrendDossier

HAS_WEASYPRINT = importlib.util.find_spec("weasyprint") is not None

DOSSIER = TrendDossier(
    id="dossier_x", category="ELECTRICITY_GRID", name="Grid build-out",
    thesis="Utilities are under-building for AI load growth.",
    demand_drivers=["data centre load growth"], winners=["GE Vernova"],
    evidence_for=["utility capex guidance up"], invalidation_criteria=["demand stalls"],
)
CANDIDATE = CompanyCandidate(
    dossier_id="dossier_x", ticker="NVDA", exchange="NASDAQ", exposure_type="ENABLER",
    causal_chain=["MACRO CHANGE: ...", "CASH FLOW AND EARNINGS: ..."], why_now="hyperscaler capex rising",
)


def test_daily_brief_pdf_html_contains_full_dossier_detail():
    inp = reports.DailyBriefInputs(
        run_date="2026-10-18", new_claims=[], updated_dossiers=[DOSSIER], new_candidates=[CANDIDATE],
        contradicting_evidence=[], portfolio_notes=[], next_indicators=[], emails_processed=1, emails_skipped_duplicate=0,
    )
    html = pdf_render.build_daily_brief_pdf_html(inp)
    assert "<style>" in html  # PDFs may use a real stylesheet, unlike the email
    assert "GE Vernova" in html
    assert "NVDA" in html
    assert "under-building" in html


def test_weekly_review_pdf_html_contains_scorecard_placeholder_when_unscored():
    inp = reports.WeeklyReviewInputs(
        week_ending="2026-10-18", ranked=[(DOSSIER, None)], conviction_changes=[], new_bottlenecks=[],
        improving_companies=[], deteriorating_companies=[], valuation_concerns=[], portfolio_cross_check=[],
        next_to_investigate=[], strongest_counterarguments=[],
    )
    html = pdf_render.build_weekly_review_pdf_html(inp)
    assert "Not yet scored" in html


def test_company_opportunity_pdf_html_contains_causal_chain():
    html = pdf_render.build_company_opportunity_pdf_html(CANDIDATE, DOSSIER)
    assert "CASH FLOW AND EARNINGS" in html


def test_gmail_digest_pdf_html_builds_without_error():
    html = pdf_render.build_gmail_digest_pdf_html([], {})
    assert "Gmail Research Digest" in html


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="weasyprint not installed in this environment")
def test_render_pdf_writes_a_real_pdf_file(tmp_path):
    html = pdf_render._doc("test", "<h2>Hello</h2>")
    out = pdf_render.render_pdf(html, tmp_path / "out.pdf")
    assert out.is_file()
    assert out.read_bytes().startswith(b"%PDF")


def test_build_pdf_degrades_gracefully_when_weasyprint_missing(tmp_path, monkeypatch):
    class FakeStore:
        root = tmp_path

    def _raise(*a, **k):
        raise ImportError("no module named weasyprint")

    monkeypatch.setattr(mm_main.pdf_render, "render_pdf", _raise)
    result = mm_main._build_pdf("daily_brief", "<html></html>", FakeStore(), "2026-10-18")
    assert result is None  # the email still sends, just without the attachment


def test_build_pdf_degrades_gracefully_on_any_render_failure(tmp_path, monkeypatch):
    class FakeStore:
        root = tmp_path

    def _raise(*a, **k):
        raise RuntimeError("font loading failed")

    monkeypatch.setattr(mm_main.pdf_render, "render_pdf", _raise)
    result = mm_main._build_pdf("daily_brief", "<html></html>", FakeStore(), "2026-10-18")
    assert result is None
