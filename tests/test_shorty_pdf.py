"""shorty_pdf.py's full-detail report builder -- a pure HTML string
function (no Playwright needed to test it). Rendering to an actual PDF
is exercised manually (Playwright + the pre-installed Chromium), not in
this unit-test run, same split us_agent's PDF tests use."""

from __future__ import annotations

from shorty_email import ShortyRow
from shorty_pdf import build_full_report_pdf_html


def _holdings():
    return [
        ShortyRow(ticker="DRO", company="DroneShield Limited",
                  current_pct=16.23, current_rank=1, baseline_pct=8.50, baseline_rank=4),
        ShortyRow(ticker="BHP", company="BHP Group Limited",
                  current_pct=1.23, current_rank=400, baseline_pct=None, baseline_rank=None),
    ]


def _watchlist():
    return [
        ShortyRow(ticker="ARB", company="", current_pct=9.50, current_rank=3,
                  baseline_pct=4.00, baseline_rank=55, watchlist="JM Watch List"),
        ShortyRow(ticker="XRO", company="", current_pct=None, current_rank=None,
                  baseline_pct=None, baseline_rank=None, watchlist="JM Watch List"),
    ]


def test_pdf_html_has_page_rule_and_page_number_footer():
    """Multi-page watchlist tables need a @page footer -- pins the CSS
    the Playwright render relies on (prefer_css_page_size=True)."""
    html = build_full_report_pdf_html("2026-10-12", "2026-06-30", _holdings(), _watchlist())
    assert "@page" in html
    assert "counter(page)" in html


def test_pdf_html_contains_every_holding_and_watchlist_ticker():
    html = build_full_report_pdf_html("2026-10-12", "2026-06-30", _holdings(), _watchlist())
    assert "DRO" in html and "16.23%" in html
    assert "BHP" in html and "not reported" in html
    assert "ARB" in html and "JM Watch List" in html
    assert "XRO" in html


def test_pdf_watchlist_table_shows_company_name_too():
    watchlist = [
        ShortyRow(ticker="ARB", company="Aristocrat Leisure Limited", current_pct=9.50,
                  current_rank=3, baseline_pct=4.00, baseline_rank=55, watchlist="JM Watch List"),
    ]
    html = build_full_report_pdf_html("2026-10-12", "2026-06-30", _holdings(), watchlist)
    watchlist_section = html.split("Your Watchlists")[1]
    assert "<th>Company</th>" in watchlist_section
    assert "Aristocrat Leisure Limited" in watchlist_section


def test_pdf_html_shows_watchlist_unavailable_note_instead_of_table():
    html = build_full_report_pdf_html(
        "2026-10-12", "2026-06-30", _holdings(), [],
        watchlist_unavailable_note="could not load Wally's watchlists: boom",
    )
    assert "could not load Wally" in html
    watchlist_section = html.split("Your Watchlists")[1]
    assert "<table>" not in watchlist_section


def test_pdf_html_can_use_style_blocks_unlike_the_email():
    """The email body bans <style>; the PDF explicitly may use one
    (CLAUDE.md: 'The PDF may use a stylesheet; the email may not')."""
    html = build_full_report_pdf_html("2026-10-12", "2026-06-30", _holdings(), _watchlist())
    assert "<style>" in html


def test_pdf_html_includes_top_market_callout():
    html = build_full_report_pdf_html(
        "2026-10-12", "2026-06-30", _holdings(), _watchlist(),
        top_market_ticker="DRO", top_market_company="DroneShield Limited", top_market_pct=16.23,
    )
    assert "Most shorted stock on the ASX" in html
    assert "DroneShield Limited" in html


def test_pdf_html_handles_empty_holdings_and_watchlist():
    html = build_full_report_pdf_html("2026-10-12", None, [], [])
    assert "No portfolio tickers" in html
    assert "No watchlist tickers" in html
