"""The 'Announced: <date>' line, shown only on wide-window reruns.

Running Bob a second time with FORCE_RERUN_TICKERS can pull weeks or months
of announcements for one ticker -- AHC's real case was two acquisitions six
months apart landing in the same force-rerun output, and without the actual
announcement date on each card there was no way to tell which deal a given
card was about. The normal daily run never needs this: "today" already is
the announcement date there.

Every card builder takes an optional ``announced`` string; it renders an
extra line when non-empty and is otherwise invisible (the normal daily run
passes announced="").
"""

import sys
import types
from pathlib import Path
from unittest import mock

from _stubs import stub_missing  # noqa: E402

_STUBBED = stub_missing(
    "anthropic", "playwright", "playwright.async_api", "googleapiclient",
    "googleapiclient.discovery", "googleapiclient.http",
    "google", "google.oauth2", "google.oauth2.credentials",
    "google.oauth2.service_account", "google.auth",
    "google.auth.transport", "google.auth.transport.requests",
)
if "googleapiclient.http" in _STUBBED:
    sys.modules["googleapiclient.http"].MediaInMemoryUpload = mock.MagicMock()

_pw_stub = types.ModuleType("playwright_fetch")
_pw_stub.fetch_pdf_with_playwright = None  # type: ignore[attr-defined]
sys.modules.setdefault("playwright_fetch", _pw_stub)

sys.path.insert(0, str(Path(__file__).parent.parent))

import agent  # noqa: E402


def test_helpers_are_empty_when_no_date_given():
    assert agent._announced_text_line("") == ""
    assert agent._announced_html_line("") == ""


def test_helpers_render_the_date_when_given():
    assert agent._announced_text_line("16/10/2026") == "Announced: 16/10/2026"
    assert "16/10/2026" in agent._announced_html_line("16/10/2026")
    assert "Announced" in agent._announced_html_line("16/10/2026")


def test_acquisition_card_shows_date_only_when_passed():
    analysis = {
        "ticker": "AHC", "target_name": "CareTech Systems Pty Ltd", "currency": "AUD",
        "quick_take": {
            "target": {"value": "CareTech Systems Pty Ltd"},
            "consideration": {"value": "$4.04m"},
            "multiple": {"value": "3.5x"},
            "funding": {"value": "cash + debt"},
            "strategic_fit": {"value": "fills a gap"},
        },
        "summary": "A tuck-in.", "_status": "ok",
    }
    plain = agent.build_acquisition_block("AHC", analysis, "u")
    assert "Announced" not in plain["html"]
    assert "Announced" not in plain["text"]

    dated = agent.build_acquisition_block("AHC", analysis, "u", announced="16/10/2026")
    assert "Announced 16/10/2026" in dated["html"]
    assert "Announced: 16/10/2026" in dated["text"]


def test_two_acquisitions_six_months_apart_are_distinguishable_by_date():
    """AHC's actual failure mode: a force-rerun pulling 6 months of history
    surfaces two separate acquisitions for the same ticker. Without a date on
    each card there is no way to tell them apart."""
    base = {
        "ticker": "AHC", "currency": "AUD",
        "quick_take": {
            "target": {"value": "Target A"}, "consideration": {"value": "$1m"},
            "multiple": {"value": "2x"}, "funding": {"value": "cash"},
            "strategic_fit": {"value": "fit"},
        },
        "summary": "Deal.", "_status": "ok",
    }
    april = agent.build_acquisition_block(
        "AHC", {**base, "target_name": "April Deal Pty Ltd"}, "u1", announced="15/04/2026",
    )
    october = agent.build_acquisition_block(
        "AHC", {**base, "target_name": "October Deal Pty Ltd"}, "u2", announced="16/10/2026",
    )
    assert "15/04/2026" in april["html"] and "16/10/2026" not in april["html"]
    assert "16/10/2026" in october["html"] and "15/04/2026" not in october["html"]


def test_trading_update_card_shows_date_only_when_passed():
    analysis = {
        "ticker": "DRO", "has_data": True, "currency": "AUD",
        "quick_take": {
            "headline_metric": {"value": "$261m"}, "guidance_call": {"value": "In-line"},
            "key_driver": {"value": "demand"}, "balance_sheet": {"value": "$180m cash"},
        },
        "summary": "In-line.", "_status": "ok",
    }
    plain = agent.build_trading_update_block("DRO", analysis, "u")
    assert "Announced" not in plain["html"]
    dated = agent.build_trading_update_block("DRO", analysis, "u", announced="12/10/2026")
    assert "Announced 12/10/2026" in dated["html"]


def test_4c_card_shows_date_only_when_passed():
    analysis = {
        "ticker": "MVP", "has_data": True, "period": "Q1 FY27", "currency": "AUD",
        "cash_flow": {
            "operating": {"value": "-$0.3m"}, "investing": {"value": "-$0.27m"},
            "financing": {"value": "nil"},
        },
        "cash_position": {"value": "$20.6m"},
        "runway": {"quarters": "62.6", "basis": "computed"},
        "summary": "Fine.", "_status": "ok",
    }
    plain = agent.build_4c_block("MVP", analysis, "u")
    assert "Announced" not in plain["html"]
    dated = agent.build_4c_block("MVP", analysis, "u", announced="15/10/2026")
    assert "Announced 15/10/2026" in dated["html"]


def test_fundraise_card_shows_date_only_when_passed():
    analysis = {
        "ticker": "CSL", "kind": "debt", "currency": "USD", "verdict": "opportunistic",
        "quick_take": {
            "instrument": {"value": "Bonds"}, "amount": {"value": "US$1.5bn"},
            "structure": {"value": "7yr"}, "use_of_proceeds": {"value": "refinance"},
            "cost_or_dilution": {"value": "6%"}, "balance_sheet": {"value": "+US$1.5bn"},
        },
        "summary": "Opportunistic.", "_status": "ok",
    }
    plain = agent.build_fundraise_block("CSL", analysis, "u")
    assert "Announced" not in plain["html"]
    dated = agent.build_fundraise_block("CSL", analysis, "u", announced="07/10/2026")
    assert "Announced 07/10/2026" in dated["html"]


def test_remuneration_card_shows_date_only_when_passed():
    analysis = {
        "ticker": "AHC", "plan_name": "LTI", "plan_type": "LTI", "participants": "execs",
        "verdict": "aligned", "alignment_score": "4",
        "quick_take": {
            "funding": {"value": "new issue"}, "quantum": {"value": "100%"},
            "hurdles": {"value": "TSR"}, "vesting_period": {"value": "3y"},
            "shareholder_dilution": {"value": "2%"},
        },
        "summary": "Aligned.", "_status": "ok",
    }
    plain = agent.build_remuneration_block("AHC", analysis, "u")
    assert "Announced" not in plain["html"]
    dated = agent.build_remuneration_block("AHC", analysis, "u", announced="01/09/2026")
    assert "Announced 01/09/2026" in dated["html"]


def test_results_card_shows_date_only_when_passed():
    analysis = {
        "ticker": "CAT", "period": "FY26", "period_type": "full_year", "currency": "AUD",
        "metrics": {}, "summary": "Beat.", "_status": "ok",
    }
    plain = agent.build_results_block("CAT", analysis, "u")
    assert "Announced" not in plain["html"]
    dated = agent.build_results_block("CAT", analysis, "u", announced="20/08/2026")
    assert "Announced 20/08/2026" in dated["html"]


def test_high_impact_block_shows_date_only_when_passed():
    memo = {"what_happened": "Thing happened.", "so_what": "Matters."}
    plain = agent.build_high_impact_block("BHP", "ASX Price Sensitive", memo, "u")
    assert "Announced" not in plain
    dated = agent.build_high_impact_block("BHP", "ASX Price Sensitive", memo, "u", announced="05/05/2026")
    assert "Announced: 05/05/2026" in dated
