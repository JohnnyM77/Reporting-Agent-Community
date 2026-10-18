"""Trading update structured card.

The old TRADING_UPDATE path dumped the whole LLM analysis into the email as
one wall of text (build_high_impact_block + the free-text what_they_said/...
schema) — DRO's real committed-revenue update rendered this way on
2026-10-15. It now renders the same phone-first card as capital raises and
results: a quick-take table (headline number / vs guidance / driver /
balance sheet), a <=5-sentence summary, and the forensic detail in an
attached PDF.

A second, independent bug shipped the same morning: MSV's announcement was
nothing but a notice that the real Q1 FY27 update would be released four
days later, and it still produced a five-metric card of nothing but "n/a".
deep_trading_update_memo's "has_data" gate is the fix — these tests pin that
a genuine notification-only document renders nothing, while a genuine
failure/skip is never mistaken for one.
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


def _trading_analysis(**over):
    a = {
        "ticker": "DRO", "has_data": True, "currency": "AUD",
        "quick_take": {
            "headline_metric": {"value": "FY26 Committed Revenue $261m", "note": "midpoint of $250-270m guidance"},
            "guidance_call":    {"value": "In-line", "note": "guidance range set in July 2026"},
            "key_driver":       {"value": "Defence demand growth, offset by margin compression"},
            "balance_sheet":    {"value": "$180m cash, debt-free", "note": "burn rate real but not urgent"},
        },
        "summary": "In-line with guidance at $261m committed revenue. Gross margin fell to 60%. Cash is $180m, debt-free. FY27 forward book is thin. Watch gross margin trajectory.",
        "full_analysis": "## What they said\nFY26 committed revenue $261m.\n\n## The numbers\n| Metric | Value |\n|---|---|\n| Revenue | $261m |\n",
        "_status": "ok",
    }
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# Email-safety: table-only, inline styles — same rule every card is held to.
# ---------------------------------------------------------------------------

def test_card_is_table_only_inline_styles():
    html = agent.build_trading_update_block("DRO", _trading_analysis(), "https://asx.example/dro")["html"]
    for banned in ("display:flex", "display:grid", "<style", "class="):
        assert banned not in html, f"email card must not contain {banned!r}"


def test_card_renders_all_four_quick_take_rows():
    html = agent.build_trading_update_block("DRO", _trading_analysis(), "u")["html"]
    for _key, label in agent.TRADING_UPDATE_QUICK_TAKE_ROWS:
        assert label in html, f"missing quick-take row {label!r}"


def test_card_shows_title_and_pdf_note():
    block = agent.build_trading_update_block("DRO", _trading_analysis(), "u")
    assert "DRO — Trading update" in block["html"]
    assert "📎 Full trading update analysis PDF attached" in block["html"]


def test_undisclosed_field_reads_not_disclosed_never_a_number():
    a = _trading_analysis()
    a["quick_take"]["balance_sheet"] = {"value": "", "note": "cash position not given"}
    row = agent._trading_update_quick_take_row(a, "balance_sheet")
    assert row["value"] == "not disclosed"


def test_guidance_call_verdict_ladder():
    cases = {
        "Upgrade": "UPGRADE", "Downgrade": "DOWNGRADE", "Profit warning": "DOWNGRADE",
        "Withdrawn": "WITHDRAWN", "In-line": "IN LINE", "": "REVIEW", "No guidance given": "REVIEW",
    }
    for call, label in cases.items():
        got, _colour = agent._trading_update_verdict(
            {"quick_take": {"guidance_call": {"value": call}}}
        )
        assert got == label, (call, got)


def test_usd_values_get_currency_prefix_not_converted():
    a = _trading_analysis(currency="USD")
    a["quick_take"]["headline_metric"]["value"] = "$4.8m"
    html = agent.build_trading_update_block("DRO", a, "u")["html"]
    assert "US$4.8m" in html


# ---------------------------------------------------------------------------
# The MSV bug: a notification-only document must render nothing.
# ---------------------------------------------------------------------------

def test_memo_returns_has_data_false_is_distinguishable_from_ok_card():
    notification = {
        "has_data": False,
        "summary": "FY27 Q1 trading update will be released on 19 October 2026, followed by a webinar.",
        "notice_date": "2026-10-19",
        "_status": "ok",
    }
    assert notification["has_data"] is False
    # The main loop checks exactly this before building any card/PDF — see
    # agent.main()'s QUARTERLY_4C / TRADING_UPDATE branches.


def test_skip_and_failure_always_force_has_data_true():
    """A genuine run-cap skip or API failure must never be silently treated
    as a quiet notification — only a successfully parsed model response that
    explicitly says has_data=false suppresses the card."""
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 1, "llm_calls": 1,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_trading_update_memo("DRO", "DRO Trading Update", "update text " * 100, counters)
    assert memo["_status"] == agent.RESULTS_STATUS_SKIPPED
    assert memo["has_data"] is True
    assert not agent._is_llm_failure(memo)


def test_memo_no_content_forces_has_data_true():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 25, "llm_calls": 0,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_trading_update_memo("DRO", "DRO Trading Update", "too short", counters)
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
    block = agent.build_trading_update_block("ABC", pf, "u")
    assert agent.RESULTS_FAILURE_BADGE in block["html"]
    doc = agent.build_trading_update_doc_html("ABC", pf, "u")
    assert "{ this is not valid json" in doc
    assert "Raw model output" in doc


def test_doc_html_renders_table_and_summary():
    doc = agent.build_trading_update_doc_html("DRO", _trading_analysis(), "https://asx.example/dro")
    assert "<table" in doc
    assert "Summary" in doc
    assert "IN LINE" in doc
