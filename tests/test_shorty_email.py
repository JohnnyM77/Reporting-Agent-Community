"""Shorty's email body: table/div-based with inline styles only, same rule
every other agent's email follows (CLAUDE.md 'Email HTML constraints').
No <style> blocks, no class=, no display:flex/grid -- Gmail/Outlook strip
<style> and mishandle flexbox/grid.

Also pins the "sexy" card redesign: the email leads with a curated "most
shorted" + "biggest movers" set (mirroring Bob/Slinger's results-card
look) rather than one flat alphabetical table, with a full sorted
reference table underneath so nothing is lost."""

from __future__ import annotations

import pytest

from shorty_email import ShortyRow, build_email, build_failure_email


def _rows():
    return [
        ShortyRow(ticker="DRO", company="DroneShield Limited",
                  current_pct=16.23, current_rank=1,
                  baseline_pct=8.50, baseline_rank=4),
        ShortyRow(ticker="BHP", company="BHP Group Limited",
                  current_pct=1.23, current_rank=400,
                  baseline_pct=None, baseline_rank=None),
        ShortyRow(ticker="CSL", company="CSL Limited",
                  current_pct=0.50, current_rank=900,
                  baseline_pct=4.00, baseline_rank=120),
        ShortyRow(ticker="AHC", company="Austco Healthcare Limited",
                  current_pct=None, current_rank=None,
                  baseline_pct=None, baseline_rank=None),
    ]


def test_email_html_has_no_flex_grid_style_or_class():
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows(),
                              top_market_ticker="DRO", top_market_company="DroneShield Limited",
                              top_market_pct=16.23)
    assert "<style" not in html
    assert " class=" not in html
    assert "display:flex" not in html and "display: flex" not in html
    assert "display:grid" not in html and "display: grid" not in html


def test_failure_email_also_has_no_flex_grid_style_or_class():
    _, _, html = build_failure_email("no report found")
    assert "<style" not in html
    assert " class=" not in html
    assert "display:flex" not in html and "display: flex" not in html


def test_change_pp_is_the_difference_not_a_ratio():
    row = ShortyRow(ticker="DRO", company="DroneShield",
                     current_pct=16.23, current_rank=1,
                     baseline_pct=8.50, baseline_rank=4)
    assert row.change_pp == pytest.approx(16.23 - 8.50)


def test_change_pp_is_none_when_either_side_is_missing():
    row = ShortyRow(ticker="BHP", company="BHP", current_pct=1.23, current_rank=400,
                     baseline_pct=None, baseline_rank=None)
    assert row.change_pp is None


def test_html_renders_not_reported_rather_than_zero_for_missing_data():
    """A ticker absent from a report must never be rendered as 0% -- that
    would silently claim 'no short interest' when the real answer is
    'no data'. AHC has neither current nor baseline data."""
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows())
    assert "not reported" in html
    assert "0.00%" not in html


def test_most_shorted_section_leads_with_the_highest_pct_ticker():
    """DRO (16.23%) must appear in the 'most shorted' card section, which
    is rendered before the full reference table."""
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows())
    most_shorted_idx = html.find("MOST SHORTED")
    reference_idx = html.find("sorted by current short")
    assert most_shorted_idx != -1
    assert reference_idx != -1
    assert most_shorted_idx < reference_idx
    # DRO's card (with its rank badge) appears before the reference table
    dro_card_idx = html.find("#1 on ASX")
    assert dro_card_idx != -1
    assert dro_card_idx < reference_idx


def test_movers_section_ranks_by_absolute_change_not_direction():
    """DRO moved +7.73pp, CSL moved -3.50pp -- both are 'big moves' even
    though one grew and one shrank, so both should appear as movers."""
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows())
    movers_idx = html.find("BIGGEST MOVERS")
    assert movers_idx != -1
    # Both tickers must appear somewhere after the movers header (as cards)
    tail = html[movers_idx:]
    assert "DRO" in tail
    assert "CSL" in tail


def test_movers_section_omitted_when_baseline_unavailable():
    _, _, html = build_email(
        "2026-10-12", None, _rows(),
        baseline_unavailable_note="FY-start baseline unavailable: no report found.",
    )
    assert "BIGGEST MOVERS" not in html


def test_reference_table_sorts_by_current_pct_descending_not_reported_last():
    rows = _rows()
    _, text, _ = build_email("2026-10-12", "2026-06-30", rows)
    # Extract the plain-text full table block (after the header row)
    header_idx = text.index("Ticker  ")
    table_text = text[header_idx:]
    dro_pos = table_text.index("DRO")
    bhp_pos = table_text.index("BHP")
    csl_pos = table_text.index("CSL")
    ahc_pos = table_text.index("AHC")
    # DRO (16.23) > BHP (1.23) > CSL (0.50) > AHC (not reported, last)
    assert dro_pos < bhp_pos < csl_pos < ahc_pos


def test_html_shows_both_tickers_and_their_current_percentages():
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows())
    assert "DRO" in html and "16.23%" in html
    assert "BHP" in html and "1.23%" in html


def test_subject_includes_report_date():
    subject, _, _ = build_email("2026-10-12", "2026-06-30", _rows())
    assert "2026-10-12" in subject


def test_text_body_has_a_plain_table_fallback():
    _, text, _ = build_email("2026-10-12", "2026-06-30", _rows())
    assert "DRO" in text
    assert "16.23%" in text


def test_empty_rows_render_without_crashing():
    _, text, html = build_email("2026-10-12", "2026-06-30", [])
    assert "No portfolio tickers" in html
    assert isinstance(text, str)


# --- watchlist sections ------------------------------------------------

def _watchlist_rows():
    return [
        ShortyRow(ticker="ARB", company="", current_pct=9.50, current_rank=3,
                  baseline_pct=4.00, baseline_rank=55, watchlist="JM Watch List"),
        ShortyRow(ticker="XRO", company="", current_pct=0.80, current_rank=600,
                  baseline_pct=6.50, baseline_rank=10, watchlist="JM Watch List"),
        ShortyRow(ticker="AD8", company="", current_pct=None, current_rank=None,
                  baseline_pct=None, baseline_rank=None, watchlist="Aussie Tech Watchlist"),
    ]


def test_watchlist_section_shows_ticker_and_watchlist_name():
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows(),
                              watchlist_rows=_watchlist_rows())
    assert "MOST SHORTED IN YOUR WATCHLISTS" in html
    assert "ARB" in html
    assert "JM Watch List" in html


def test_watchlist_card_shows_company_name_alongside_watchlist_badge():
    """A watchlist ticker now carries a company name (derived from the ASIC
    report, not tickers.yaml) -- the card must show both it and which
    watchlist it's from, not force a choice between them."""
    rows = [
        ShortyRow(ticker="ARB", company="Aristocrat Leisure Limited",
                  current_pct=9.50, current_rank=3,
                  baseline_pct=4.00, baseline_rank=55, watchlist="JM Watch List"),
    ]
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows(), watchlist_rows=rows)
    assert "Aristocrat Leisure Limited" in html
    assert "JM Watch List" in html


def test_watchlist_movers_includes_both_directions():
    """ARB moved +5.50pp, XRO moved -5.70pp -- both are big moves."""
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows(),
                              watchlist_rows=_watchlist_rows())
    movers_idx = html.find("BIGGEST MOVERS IN YOUR WATCHLISTS")
    assert movers_idx != -1
    tail = html[movers_idx:]
    assert "ARB" in tail
    assert "XRO" in tail


def test_watchlist_section_omitted_when_no_watchlist_rows():
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows())
    assert "YOUR WATCHLISTS" not in html


def test_watchlist_unavailable_note_shown_instead_of_sections():
    _, _, html = build_email(
        "2026-10-12", "2026-06-30", _rows(),
        watchlist_rows=_watchlist_rows(),
        watchlist_unavailable_note="could not load Wally's watchlists: boom",
    )
    assert "could not load Wally" in html
    assert "MOST SHORTED IN YOUR WATCHLISTS" not in html


def test_pdf_attached_adds_footer_note():
    _, text, html = build_email("2026-10-12", "2026-06-30", _rows(), pdf_attached=True)
    assert "attached as a PDF" in html
    assert "attached as a PDF" in text


def test_pdf_not_attached_has_no_footer_note():
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows(), pdf_attached=False)
    assert "attached as a PDF" not in html


def test_watchlist_email_html_still_has_no_flex_grid_style_or_class():
    _, _, html = build_email("2026-10-12", "2026-06-30", _rows(),
                              watchlist_rows=_watchlist_rows(), pdf_attached=True)
    assert "<style" not in html
    assert " class=" not in html
    assert "display:flex" not in html and "display: flex" not in html
    assert "display:grid" not in html and "display: grid" not in html
