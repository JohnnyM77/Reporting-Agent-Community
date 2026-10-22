"""NHC's real failure (2026-10-18): "New Hope and Malabar to combine" was a
~$1.3bn scrip-funded business combination -- economically an acquisition
funded by what is, in substance, a massive capital raise -- and Bob missed
every one of the three related documents:

- "New Hope and Malabar to combine" (the primary release): matched neither
  is_price_sensitive_title nor any classify_from_title_only bucket ("combine"
  is not "acquisition"/"merger"/"scheme"/"takeover"/"transaction"), so it
  fell straight through to a bare FYI line.
- "Presentation on New Hope and Malabar to Combine": matched
  is_price_sensitive_title via "presentation" but classified as OTHER, so it
  rendered as a generic "price-sensitive headline" MATERIAL two-liner with
  zero analysis.
- "Proposed issue of securities - NHC" (the ~$1.3bn consideration share
  issuance): matched neither list at all ("issue of securities" is not
  "issue of shares"), so it too was FYI-only.

This file pins the three fixes: broadened classification ("combin", "issue
of securities" / "issue of new shares"), the single-trigger acquisition
bundle (so the three documents are analysed together as one deal instead of
fragmenting or being missed), and the new "capital raise check" quick-take
row that makes the dual acquisition/capital-raise nature explicit in the
card itself.
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


# ---------------------------------------------------------------------------
# Classification: "combine"/"combination" is acquisition-class language;
# "issue of securities"/"issue of new shares" is capital-raise-class language.
# ---------------------------------------------------------------------------

def test_combine_titles_classify_as_acquisition():
    assert agent.classify_from_title_only("New Hope and Malabar to combine") == "ACQUISITION"
    assert agent.classify_from_title_only(
        "Presentation on New Hope and Malabar to Combine"
    ) == "ACQUISITION"
    assert agent.classify_from_title_only("Proposal to combine with Acme Ltd") == "ACQUISITION"


def test_combine_titles_are_price_sensitive():
    assert agent.is_price_sensitive_title("New Hope and Malabar to combine") is True


def test_issue_of_securities_classifies_as_capital_raise():
    assert agent.classify_from_title_only("Proposed issue of securities - NHC") == "CAPITAL_OR_DEBT_RAISE"
    assert agent.classify_from_title_only("Issue of new shares") == "CAPITAL_OR_DEBT_RAISE"
    assert agent.is_price_sensitive_title("Proposed issue of securities - NHC") is True


def test_existing_acquisition_keywords_unaffected():
    """The pre-existing keywords (AHC's real titles) must keep classifying
    exactly as before -- this change only adds coverage, never narrows it."""
    assert agent.classify_from_title_only("Austco Healthcare to acquire CareTech Systems") == "ACQUISITION"
    assert agent.classify_from_title_only("Austco Healthcare to acquire RTM Solutions") == "ACQUISITION"


# ---------------------------------------------------------------------------
# Bundling: one trigger + same-day side documents = one deal, analysed once.
# ---------------------------------------------------------------------------

def _nhc_items():
    return [
        {"ticker": "NHC", "title": "New Hope and Malabar to combine",
         "url": "u-release", "date": "18/10/2026"},
        {"ticker": "NHC", "title": "Presentation on New Hope and Malabar to Combine",
         "url": "u-presentation", "date": "18/10/2026"},
        {"ticker": "NHC", "title": "Proposed issue of securities - NHC",
         "url": "u-issue", "date": "18/10/2026"},
        {"ticker": "NHC", "title": "Change of Director's Interest Notice",
         "url": "u-unrelated", "date": "18/10/2026"},
    ]


def test_nhc_bundle_includes_release_presentation_and_share_issue():
    bundle = agent.likely_acquisition_bundle_items(_nhc_items())
    urls = {it["url"] for it in bundle}
    assert urls == {"u-release", "u-presentation", "u-issue"}
    # The unrelated director's-interest notice must not be swept in.
    assert "u-unrelated" not in urls


def test_bundle_requires_the_trigger_itself_first():
    bundle = agent.likely_acquisition_bundle_items(_nhc_items())
    assert bundle[0]["url"] == "u-release"


def test_side_document_on_a_different_day_is_not_bundled():
    items = _nhc_items()
    items[1]["date"] = "20/10/2026"  # presentation lodged two days later
    bundle = agent.likely_acquisition_bundle_items(items)
    urls = {it["url"] for it in bundle}
    assert "u-presentation" not in urls
    assert "u-release" in urls and "u-issue" in urls


def test_no_trigger_means_no_bundle():
    items = [{"ticker": "NHC", "title": "Proposed issue of securities - NHC",
              "url": "u-issue", "date": "18/10/2026"}]
    assert agent.likely_acquisition_bundle_items(items) == []


def test_two_distinct_acquisitions_same_day_do_not_bundle():
    """AHC's real case: two separate, unrelated acquisitions announced the
    same morning must NOT be merged into one card -- each keeps its own
    target and is left to the per-item loop exactly as before."""
    items = [
        {"ticker": "AHC", "title": "Austco Healthcare to acquire CareTech Systems",
         "url": "u-caretech", "date": "16/10/2026"},
        {"ticker": "AHC", "title": "Austco Healthcare to acquire RTM Solutions",
         "url": "u-rtm", "date": "16/10/2026"},
    ]
    assert agent.likely_acquisition_bundle_items(items) == []


# ---------------------------------------------------------------------------
# The "capital raise check" quick-take row -- the structured dual-nature
# output the user asked for.
# ---------------------------------------------------------------------------

def _nhc_analysis(**over):
    a = {
        "ticker": "NHC", "target_name": "Malabar Resources", "currency": "AUD",
        "quick_take": {
            "target": {"value": "Malabar Resources (coal, JV partner)"},
            "consideration": {"value": "A$1.3bn in new NHC shares issued to Malabar shareholders"},
            "multiple": {"value": "not disclosed in this announcement"},
            "funding": {"value": "100% scrip, no cash/debt"},
            "capital_raise_check": {
                "value": "Yes — A$1.3bn in new NHC shares issued to Malabar shareholders (~45% of shares on issue)",
                "note": "no cash underwritten, no shareholder opportunity to participate pro-rata",
            },
            "strategic_fit": {"value": "Combines adjoining JV interests under one roof"},
        },
        "summary": "A$1.3bn scrip combination with Malabar, NHC's existing JV partner.",
        "_status": "ok",
    }
    a.update(over)
    return a


def test_acquisition_card_includes_capital_raise_check_row():
    html = agent.build_acquisition_block("NHC", _nhc_analysis(), "u")["html"]
    assert "Capital raise check" in html
    assert "A$1.3bn" in html


def test_capital_raise_check_is_one_of_the_locked_rows():
    keys = [k for k, _label in agent.ACQUISITION_QUICK_TAKE_ROWS]
    assert "capital_raise_check" in keys


def test_undisclosed_capital_raise_check_reads_not_disclosed():
    a = _nhc_analysis()
    a["quick_take"]["capital_raise_check"] = {"value": ""}
    row = agent._acquisition_quick_take_row(a, "capital_raise_check")
    assert row["value"] == "not disclosed"


# ---------------------------------------------------------------------------
# deep_acquisition_memo: pdf_attachments is backward compatible with the
# existing single-item skip/no-content paths.
# ---------------------------------------------------------------------------

def test_memo_without_pdf_attachments_still_skips_cleanly():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 1, "llm_calls": 1,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_acquisition_memo("NHC", "New Hope and Malabar to combine", "deal text " * 100, counters)
    assert memo["_status"] == agent.RESULTS_STATUS_SKIPPED
    assert not agent._is_llm_failure(memo)


def test_memo_no_content_when_no_pdfs_and_thin_text():
    counters = {
        "MAX_LLM_CALLS_PER_RUN": 25, "llm_calls": 0,
        "MAX_PDFS_PER_RUN": 10, "pdfs_downloaded": 0,
    }
    memo = agent.deep_acquisition_memo(
        "NHC", "New Hope and Malabar to combine", "too short", counters, pdf_attachments=None,
    )
    assert memo["_status"] == agent.RESULTS_STATUS_NO_CONTENT
