"""Appendix 4C / 5B quarterly cash flow structured card.

MVP's real Q1 FY27 Appendix 4C was previously lumped in with the generic
TRADING_UPDATE path (classified by the same "quarterly" keyword as a bare
revenue update) and rendered as one wall of prose with no runway figure
anywhere in it — despite the underlying announcement containing exactly the
cash flow schedule needed to answer "how many quarters of funding are
left". It now gets its own template: a short operating/investing/financing
cash-flow table, the cash position, and the Question 8 runway figure as the
header verdict pill, with the forensic cash-flow walk in an attached PDF.

Same has_data gate as the trading-update card: a "the 4C will be released
on <date>" notice produces nothing.
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


def _4c_analysis(**over):
    a = {
        "ticker": "MVP", "has_data": True, "period": "Q1 FY27", "currency": "AUD",
        "cash_flow": {
            "operating": {"value": "-$0.3m", "ytd": "-$0.3m", "note": "Item 1.9"},
            "investing": {"value": "-$0.27m", "ytd": "-$0.27m", "note": "Item 2 — PP&E and IP"},
            "financing": {"value": "nil", "ytd": "nil", "note": "Item 3"},
        },
        "cash_position": {"value": "$20.6m", "note": "down from $21.4m opening"},
        "related_party_payments": {"value": "nil"},
        "runway": {
            "quarters": "62.6",
            "basis": "computed: cash at quarter end divided by net operating outflow this quarter",
            "note": "operating cash flow close to break-even this quarter",
        },
        "summary": "62.6 quarters of runway — not remotely urgent. Operating cash outflow narrowed to $0.3m. Investing spend minimal. No financing activity this quarter. Watch respiratory segment softness.",
        "full_analysis": "## Cash flow walk\n| Line | This quarter | YTD |\n|---|---|---|\n| Operating | -$0.3m | -$0.3m |\n",
        "_status": "ok",
    }
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# Email-safety: table-only, inline styles.
# ---------------------------------------------------------------------------

def test_card_is_table_only_inline_styles():
    html = agent.build_4c_block("MVP", _4c_analysis(), "https://asx.example/mvp")["html"]
    for banned in ("display:flex", "display:grid", "<style", "class="):
        assert banned not in html, f"email card must not contain {banned!r}"


def test_card_renders_cashflow_rows_cash_position_and_runway():
    html = agent.build_4c_block("MVP", _4c_analysis(), "u")["html"]
    for _key, label in agent.QUARTERLY_4C_CASHFLOW_ROWS:
        assert label in html, f"missing cash flow row {label!r}"
    assert "Cash at quarter end" in html
    assert "Runway" in html
    assert "62.6 quarters" in html


def test_card_title_shows_period_and_pdf_note():
    block = agent.build_4c_block("MVP", _4c_analysis(), "u")
    assert "MVP — Q1 FY27 cash flow (4C)" in block["html"]
    assert "📎 Full cash flow analysis PDF attached" in block["html"]


# ---------------------------------------------------------------------------
# Runway verdict ladder — the headline question for a small-cap 4C.
# ---------------------------------------------------------------------------

def test_runway_verdict_ladder():
    cases = {
        "1.0": "URGENT", "1.9": "URGENT",
        "2.0": "WATCH", "3.9": "WATCH",
        "4.0": "ADEQUATE", "7.9": "ADEQUATE",
        "8.0": "LONG RUNWAY", "62.6": "LONG RUNWAY",
    }
    for quarters, label in cases.items():
        got, _colour = agent._4c_runway_verdict({"runway": {"quarters": quarters}})
        assert got == label, (quarters, got)


def test_runway_na_when_operating_cashflow_positive_reads_self_funded():
    got, _colour = agent._4c_runway_verdict({"runway": {"quarters": "n/a"}})
    assert got == "SELF-FUNDED"


def test_runway_missing_or_unparseable_reads_review_not_clean():
    got, _colour = agent._4c_runway_verdict({"runway": {}})
    assert got == "REVIEW"
    got, _colour = agent._4c_runway_verdict({})
    assert got == "REVIEW"


def test_runway_line_renders_quarters_and_basis():
    row = agent._4c_runway_line(_4c_analysis())
    assert row["value"] == "62.6 quarters"
    assert "computed" in row["sub"]


# ---------------------------------------------------------------------------
# Cash flow row normalisation — n/a never invented, YTD shown when it differs.
# ---------------------------------------------------------------------------

def test_cashflow_row_shows_ytd_when_it_differs_from_this_quarter():
    a = _4c_analysis()
    a["cash_flow"]["operating"] = {"value": "-$0.3m", "ytd": "-$1.1m", "note": "Item 1.9"}
    row = agent._4c_cashflow_row(a, "operating")
    assert row["value"] == "-$0.3m"
    assert "YTD -$1.1m" in row["sub"]


def test_cashflow_row_missing_figure_is_na_never_guessed():
    a = _4c_analysis()
    a["cash_flow"]["financing"] = {"value": "", "note": ""}
    row = agent._4c_cashflow_row(a, "financing")
    assert row["value"] == "n/a"


# ---------------------------------------------------------------------------
# The notification-only gate (same bug class as MSV, for a 4C notice).
# ---------------------------------------------------------------------------

def test_skip_and_failure_always_force_has_data_true():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 1, "llm_calls": 1,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_4c_memo("MVP", "MVP Appendix 4C", "cash flow text " * 100, counters)
    assert memo["_status"] == agent.RESULTS_STATUS_SKIPPED
    assert memo["has_data"] is True
    assert not agent._is_llm_failure(memo)


def test_memo_no_content_forces_has_data_true():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 25, "llm_calls": 0,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_4c_memo("MVP", "MVP Appendix 4C", "too short", counters)
    assert memo["_status"] == agent.RESULTS_STATUS_NO_CONTENT
    assert memo["has_data"] is True


# ---------------------------------------------------------------------------
# A half-broken analysis must never look like a clean card.
# ---------------------------------------------------------------------------

def test_parse_error_renders_analysis_failed_not_a_clean_card():
    pf = {
        "has_data": True,
        "summary": f"{agent.LLM_FAILURE_FLAG} (model returned unparseable output).",
        "_status": "parse_error",
        "_raw_text": "{ this is not valid json",
    }
    block = agent.build_4c_block("ABC", pf, "u")
    assert agent.RESULTS_FAILURE_BADGE in block["html"]
    doc = agent.build_4c_doc_html("ABC", pf, "u")
    assert "{ this is not valid json" in doc
    assert "Raw model output" in doc


def test_doc_html_renders_cashflow_table_and_summary():
    doc = agent.build_4c_doc_html("MVP", _4c_analysis(), "https://asx.example/mvp")
    assert "<table" in doc
    assert "Summary" in doc
    assert "62.6 quarters" in doc
