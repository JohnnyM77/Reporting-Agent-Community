"""Capital raise / debt raise structured card.

The old CAPITAL_OR_DEBT_RAISE path dumped the whole LLM analysis into the email
as one wall of text. It now renders the same phone-first card as results and
remuneration: a verdict pill, a locked six-row quick-take, a <=5-sentence
summary, and the forensic detail in an attached PDF. These tests pin the card's
shape, the email-safety invariants, the "never guess a balance-sheet figure"
rule, and that a parse failure still reads as a failure.
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


def _debt_analysis(**over):
    a = {
        "ticker": "CSL", "kind": "debt", "currency": "USD", "verdict": "opportunistic",
        "quick_take": {
            "instrument": {"value": "Debt - investment-grade bonds", "note": "guaranteed by CSL"},
            "amount": {"value": "US$1.5bn", "note": "144A/Reg S"},
            "structure": {"value": "US$500m 7yr 5.95% + US$1,000m 10yr 6.20%", "note": "fixed"},
            "use_of_proceeds": {"value": "Refinance existing debt + GCP"},
            "cost_or_dilution": {"value": "~6.1% wtd avg, fixed", "note": "no equity issued"},
            "balance_sheet": {"value": "Gross debt +US$1.5bn; net ~neutral if refinancing"},
        },
        "summary": "Opportunistic liability management, not a rescue. US$1.5bn of IG bonds.",
        "full_analysis": "## Verdict\nOpportunistic.\n\n## What was raised\n| Tranche | Size |\n|---|---|\n| A | US$500m |\n",
        "_status": "ok",
    }
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# Email-safety: the card must be table-only, inline styles (same rule the
# results/remuneration cards are held to — a test, not a convention).
# ---------------------------------------------------------------------------

def test_card_is_table_only_inline_styles():
    html = agent.build_fundraise_block("CSL", _debt_analysis(), "https://asx.example/csl")["html"]
    for banned in ("display:flex", "display:grid", "<style", "class="):
        assert banned not in html, f"email card must not contain {banned!r}"


def test_card_renders_all_six_quick_take_rows():
    html = agent.build_fundraise_block("CSL", _debt_analysis(), "u")["html"]
    for _key, label in agent.FUNDRAISE_QUICK_TAKE_ROWS:
        assert label in html, f"missing quick-take row {label!r}"


def test_card_shows_verdict_pill_and_title():
    block = agent.build_fundraise_block("CSL", _debt_analysis(), "u")
    assert "OPPORTUNISTIC" in block["html"]
    assert "CSL — Debt raise" in block["html"]
    assert "📎 Full raise analysis PDF attached" in block["html"]


def test_equity_raise_titles_and_labels_as_capital_raise():
    html = agent.build_fundraise_block(
        "XYZ", _debt_analysis(kind="equity", verdict="rescue"), "u"
    )["html"]
    assert "XYZ — Capital raise" in html
    assert "RESCUE" in html


# ---------------------------------------------------------------------------
# The whole point: never present a guessed balance-sheet figure.
# ---------------------------------------------------------------------------

def test_undisclosed_leverage_reads_not_disclosed_never_a_number():
    a = _debt_analysis()
    a["quick_take"]["balance_sheet"] = {"value": "", "note": "prior net debt not given"}
    row = agent._fundraise_quick_take_row(a, "balance_sheet")
    assert row["value"] == "not disclosed"


def test_verdict_ladder_maps_to_the_four_signals():
    cases = {
        "opportunistic": "OPPORTUNISTIC", "neutral": "NEUTRAL",
        "defensive": "DEFENSIVE", "rescue": "RESCUE", "": "REVIEW", "weird": "REVIEW",
    }
    for verdict, label in cases.items():
        got, _colour = agent._fundraise_verdict({"verdict": verdict})
        assert got == label, (verdict, got)


def test_usd_values_get_currency_prefix_not_converted():
    html = agent.build_fundraise_block("CSL", _debt_analysis(), "u")["html"]
    # US$ stays US$ — the card never converts a reporting currency.
    assert "US$1.5bn" in html


# ---------------------------------------------------------------------------
# A half-broken analysis must never look like a clean card.
# ---------------------------------------------------------------------------

def test_parse_error_renders_analysis_failed_not_a_clean_card():
    pf = {
        "summary": f"{agent.LLM_FAILURE_FLAG} (model returned unparseable output).",
        "_status": "parse_error",
        "_raw_text": "{ this is not valid json",
    }
    block = agent.build_fundraise_block("ABC", pf, "u")
    assert agent.RESULTS_FAILURE_BADGE in block["html"]
    assert "OPPORTUNISTIC" not in block["html"]
    # Raw model output is preserved verbatim in the PDF, nothing lost.
    doc = agent.build_fundraise_doc_html("ABC", pf, "u")
    assert "{ this is not valid json" in doc
    assert "Raw model output" in doc


def test_doc_html_renders_tranche_table_and_summary():
    doc = agent.build_fundraise_doc_html("CSL", _debt_analysis(), "https://asx.example/csl")
    assert "<table" in doc and "Tranche" in doc          # full_analysis markdown table
    assert "Summary" in doc
    assert "OPPORTUNISTIC" in doc


# ---------------------------------------------------------------------------
# deep_capital_memo: skip and failure are distinct and tagged, like results.
# ---------------------------------------------------------------------------

def test_memo_skip_is_tagged_and_not_a_failure():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 1, "llm_calls": 1,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_capital_memo("NHC", "NHC Entitlement Offer", "raise text " * 100, counters)
    assert memo["_status"] == agent.RESULTS_STATUS_SKIPPED
    assert memo["summary"] == agent.LLM_SKIP_MESSAGE
    assert not agent._is_llm_failure(memo)


def test_memo_no_content_when_no_pdf_and_thin_text():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 25, "llm_calls": 0,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_capital_memo("NHC", "NHC Placement", "too short", counters)
    assert memo["_status"] == agent.RESULTS_STATUS_NO_CONTENT


# ---------------------------------------------------------------------------
# EODHD prior-balance-sheet enrichment
# ---------------------------------------------------------------------------

_PROFILE = {
    "as_of": "2026-06-30", "period": "quarterly", "currency": "USD",
    "gross_debt": 1.23e10, "cash": 2.3e9, "net_debt": 9.9e9,
    "total_equity": 1.55e10, "ebitda": 5.0e9,
    "net_debt_to_ebitda": 1.98, "gearing": 0.639, "source": "EODHD",
}


def test_fmt_money_is_compact_and_never_converts():
    assert agent._fmt_money(1.5e9, "USD") == "US$1.5bn"
    assert agent._fmt_money(9.5e8, "USD") == "US$950m"
    assert agent._fmt_money(-1.2e8, "AUD") == "-A$120m"
    assert agent._fmt_money(None, "USD") == "n/a"


def test_card_appends_prior_balance_sheet_row_when_profile_present():
    a = _debt_analysis(debt_profile=_PROFILE)
    html = agent.build_fundraise_block("CSL", a, "u")["html"]
    assert "Prior balance sheet" in html
    assert "Net debt US$9.9bn" in html and "2.0x EBITDA" in html
    assert "gearing 64%" in html
    assert "EODHD, as of 2026-06-30" in html


def test_card_has_no_prior_row_without_a_profile():
    html = agent.build_fundraise_block("CSL", _debt_analysis(), "u")["html"]
    assert "Prior balance sheet" not in html


def test_pdf_prior_balance_sheet_is_labelled_before_and_from_eodhd():
    doc = agent.build_fundraise_doc_html("CSL", _debt_analysis(debt_profile=_PROFILE), "u")
    assert "Prior balance sheet" in doc
    assert "Net Debt / EBITDA" in doc and "2.0x" in doc
    assert "Gearing" in doc and "64%" in doc
    # It must be unambiguous this is the pre-raise baseline, not from the release.
    assert "before" in doc.lower() and "EODHD" in doc
    assert "not a figure from the announcement" in doc


def test_prompt_block_gives_real_figures_and_forbids_quick_take_leakage():
    block = agent._debt_profile_prompt_block(_PROFILE)
    assert "US$9.9bn" in block and "2.0x" in block  # net debt and ND/EBITDA (rounded)
    assert "NOT from this announcement" in block
    assert "Do NOT put these prior figures in the quick_take" in block


def test_fetch_debt_profile_is_best_effort_and_never_raises(monkeypatch):
    # EODHD unconfigured -> None, no exception, card renders without it.
    import shared.eodhd as eodhd
    monkeypatch.setattr(eodhd, "is_configured", lambda: False)
    assert agent.fetch_debt_profile("CSL") is None

    # A raising EODHD call is swallowed to None (daily path must never break).
    monkeypatch.setattr(eodhd, "is_configured", lambda: True)
    def _boom(*a, **k):
        raise RuntimeError("eodhd down")
    monkeypatch.setattr(eodhd, "debt_profile", _boom)
    assert agent.fetch_debt_profile("CSL") is None
