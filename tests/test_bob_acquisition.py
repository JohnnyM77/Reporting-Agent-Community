"""Acquisition structured card.

The old ACQUISITION path dumped the whole LLM analysis into the email as one
wall of text (build_high_impact_block + the free-text deal_summary/
what_they_bought/... schema). AHC's real CareTech + RTM acquisitions
rendered this way on 2026-10-16 -- two long unstructured memos back to back
in the same digest. It now renders the same phone-first card as capital
raises and trading updates: a locked 5-row quick-take (target,
consideration, multiple, funding, strategic fit), a <=5-sentence summary,
and the forensic detail in an attached PDF.
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


def _acquisition_analysis(**over):
    a = {
        "ticker": "AHC", "target_name": "CareTech Systems Pty Ltd", "currency": "AUD",
        "quick_take": {
            "target":        {"value": "CareTech Systems Pty Ltd", "note": "Brisbane nurse call product designer"},
            "consideration": {"value": "$4.04m ($3.0m upfront + uncapped earnout)", "note": "share purchase, no scrip"},
            "multiple":      {"value": "3.5x average FY27/FY28 EBITDA", "note": "unaudited target financials"},
            "funding":       {"value": "Cash reserves + new $12m CBA facility", "note": "no dilution"},
            "strategic_fit": {"value": "Fills aged-care nurse call + wireless gap", "note": "already runs on RTM platform"},
        },
        "summary": "Disciplined tuck-in at 3.5x EBITDA for genuine product IP. 44% of revenue is intercompany and evaporates on consolidation. Funded from cash plus a new $12m facility, no dilution. Uncapped earnout and single contract manufacturer are the key risks. Inter-conditional with the RTM deal.",
        "full_analysis": "## Deal summary\nAHC acquires CareTech for $4.04m.\n\n## Price check\n| Metric | Value |\n|---|---|\n| Multiple | 3.5x |\n",
        "_status": "ok",
    }
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# Email-safety: table-only, inline styles.
# ---------------------------------------------------------------------------

def test_card_is_table_only_inline_styles():
    html = agent.build_acquisition_block("AHC", _acquisition_analysis(), "https://asx.example/ahc")["html"]
    for banned in ("display:flex", "display:grid", "<style", "class="):
        assert banned not in html, f"email card must not contain {banned!r}"


def test_card_renders_all_five_quick_take_rows():
    html = agent.build_acquisition_block("AHC", _acquisition_analysis(), "u")["html"]
    for _key, label in agent.ACQUISITION_QUICK_TAKE_ROWS:
        assert label in html, f"missing quick-take row {label!r}"


def test_card_shows_title_target_and_pdf_note():
    block = agent.build_acquisition_block("AHC", _acquisition_analysis(), "u")
    assert "AHC — Acquisition: CareTech Systems Pty Ltd" in block["html"]
    assert "📎 Full acquisition analysis PDF attached" in block["html"]


def test_two_acquisitions_same_ticker_render_as_distinct_cards():
    """AHC's real failure: CareTech and RTM are two separate deals the same
    morning. Each must carry its own target name, not collapse into one."""
    caretech = agent.build_acquisition_block("AHC", _acquisition_analysis(), "u1")
    rtm = agent.build_acquisition_block(
        "AHC", _acquisition_analysis(target_name="RTM Hold Co Pty Ltd"), "u2"
    )
    assert "CareTech Systems Pty Ltd" in caretech["html"]
    assert "RTM Hold Co Pty Ltd" in rtm["html"]
    assert "RTM Hold Co Pty Ltd" not in caretech["html"]


def test_undisclosed_field_reads_not_disclosed_never_a_number():
    a = _acquisition_analysis()
    a["quick_take"]["funding"] = {"value": "", "note": "not stated in announcement"}
    row = agent._acquisition_quick_take_row(a, "funding")
    assert row["value"] == "not disclosed"


def test_usd_values_get_currency_prefix_not_converted():
    a = _acquisition_analysis(currency="USD")
    a["quick_take"]["consideration"]["value"] = "$4.2m"
    html = agent.build_acquisition_block("AHC", a, "u")["html"]
    assert "US$4.2m" in html


# ---------------------------------------------------------------------------
# deep_acquisition_memo: skip and failure are distinct and tagged, like
# capital raises and trading updates.
# ---------------------------------------------------------------------------

def test_memo_skip_is_tagged_and_not_a_failure():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 1, "llm_calls": 1,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_acquisition_memo("AHC", "AHC to acquire CareTech", "deal text " * 100, counters)
    assert memo["_status"] == agent.RESULTS_STATUS_SKIPPED
    assert memo["summary"] == agent.LLM_SKIP_MESSAGE
    assert not agent._is_llm_failure(memo)


def test_memo_no_content_when_no_pdf_and_thin_text():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 25, "llm_calls": 0,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_acquisition_memo("AHC", "AHC to acquire CareTech", "too short", counters)
    assert memo["_status"] == agent.RESULTS_STATUS_NO_CONTENT


# ---------------------------------------------------------------------------
# A half-broken analysis must never look like a clean card.
# ---------------------------------------------------------------------------

def test_parse_error_renders_analysis_failed_not_a_clean_card():
    pf = {
        "summary": f"{agent.LLM_FAILURE_FLAG} (model returned unparseable output).",
        "_status": "parse_error",
        "_raw_text": "{ this is not valid json",
    }
    block = agent.build_acquisition_block("ABC", pf, "u")
    assert agent.RESULTS_FAILURE_BADGE in block["html"]
    doc = agent.build_acquisition_doc_html("ABC", pf, "u")
    assert "{ this is not valid json" in doc
    assert "Raw model output" in doc


def test_doc_html_renders_table_and_summary():
    doc = agent.build_acquisition_doc_html("AHC", _acquisition_analysis(), "https://asx.example/ahc")
    assert "<table" in doc and "Multiple" in doc
    assert "Summary" in doc
