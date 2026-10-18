"""
shorty_pdf.py -- the full-detail PDF attached to Shorty's email.

The email body only ever shows a curated top few (most shorted, biggest
movers) for both the portfolio and the watchlists -- the watchlist
universe alone can run past 150 tickers across Wally's five lists, far
too long for an email. This module builds the complete, sorted detail
(every portfolio holding, every watchlist ticker) as a standalone HTML
document that `shorty_agent.py` prints to PDF via Playwright and attaches
to the email -- same "glance in the email, full detail in the attachment"
split Bob/Slinger/Ned use, and the same reason: a PDF is a document people
forward, and unlike the email it's allowed a `<style>` block (CLAUDE.md's
table-only-inline-styles rule is an email-client constraint, not a PDF
one).
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from shorty_email import ShortyRow, _change_text, _esc, _sort_key

COLOR_BG = "#0B1220"
COLOR_ACCENT = "#F59E0B"


def _watchlist_sort_key(row: ShortyRow):
    # Within the watchlist table: group by watchlist, then by current %
    # descending inside each group -- easier to scan than one long list
    # sorted purely by percentage with watchlists interleaved.
    return (row.watchlist or "", row.current_pct is None, -(row.current_pct or 0), row.ticker)


def _table_rows_html(rows: List[ShortyRow], show_watchlist: bool) -> str:
    out = []
    for r in rows:
        cur = f"{r.current_pct:.2f}%" if r.current_pct is not None else "not reported"
        cur_rank = f" (#{r.current_rank})" if r.current_rank else ""
        base = f"{r.baseline_pct:.2f}%" if r.baseline_pct is not None else "not reported"
        change = r.change_pp
        change_cls = "up" if (change or 0) > 0.005 else "down" if (change or -1) < -0.005 else "flat"
        # Watchlist rows get both the company name (from the ASIC report's
        # own Product field, via _build_watchlist_rows) and which list it's
        # on; holdings rows only ever need the name.
        wl_cell = f"<td>{_esc(r.watchlist or '')}</td>" if show_watchlist else ""
        name_cell = f"<td>{_esc(r.company)}</td>"
        out.append(
            "<tr>"
            f"<td class='ticker'>{_esc(r.ticker)}</td>"
            f"{name_cell}{wl_cell}"
            f"<td class='num'>{cur}{cur_rank}</td>"
            f"<td class='num'>{base}</td>"
            f"<td class='num {change_cls}'>{_change_text(change)}</td>"
            "</tr>"
        )
    return "".join(out)


def build_full_report_pdf_html(
    report_date: str,
    baseline_date: Optional[str],
    holdings_rows: List[ShortyRow],
    watchlist_rows: List[ShortyRow],
    top_market_ticker: Optional[str] = None,
    top_market_company: Optional[str] = None,
    top_market_pct: Optional[float] = None,
    watchlist_unavailable_note: Optional[str] = None,
    generated_at: Optional[dt.datetime] = None,
) -> str:
    """Full standalone report: every holding, every watchlist ticker."""
    generated = (generated_at or dt.datetime.now(dt.timezone.utc)).strftime("%d %b %Y %H:%M UTC")

    holdings_ordered = sorted(holdings_rows, key=_sort_key)
    watchlist_ordered = sorted(watchlist_rows, key=_watchlist_sort_key)

    callout_html = ""
    if top_market_ticker:
        callout_html = (
            "<p class='callout'>Most shorted stock on the ASX on this report: "
            f"<strong>{_esc(top_market_ticker)}</strong> ({_esc(top_market_company or '')}) "
            f"at <strong>{top_market_pct:.2f}%</strong>.</p>"
        )

    holdings_table_html = (
        "<table><thead><tr><th>Ticker</th><th>Company</th><th>Current</th>"
        "<th>FY-Start</th><th>Change</th></tr></thead><tbody>"
        + (_table_rows_html(holdings_ordered, show_watchlist=False)
           if holdings_ordered else "<tr><td colspan='5'>No portfolio tickers.</td></tr>")
        + "</tbody></table>"
    )

    if watchlist_unavailable_note:
        watchlist_section_html = f"<p class='note'>{_esc(watchlist_unavailable_note)}</p>"
    elif watchlist_ordered:
        watchlist_section_html = (
            "<table><thead><tr><th>Ticker</th><th>Company</th><th>Watchlist</th><th>Current</th>"
            "<th>FY-Start</th><th>Change</th></tr></thead><tbody>"
            + _table_rows_html(watchlist_ordered, show_watchlist=True)
            + "</tbody></table>"
        )
    else:
        watchlist_section_html = "<p class='note'>No watchlist tickers to report.</p>"

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Shorty -- ASX Short Interest -- {_esc(report_date)}</title>
<style>
  @page {{ size: A4; margin: 16mm 14mm 18mm 14mm; }}
  @page {{ @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 9px; color: #94A3B8; }} }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', Arial, sans-serif;
    color: #0F172A;
    margin: 0;
    font-size: 12px;
  }}
  .cover {{
    background: {COLOR_BG};
    color: #E5E7EB;
    padding: 20px 24px;
    border-radius: 0 0 10px 10px;
    margin-bottom: 16px;
  }}
  .cover .name {{ font-size: 26px; font-weight: 900; }}
  .cover .sub {{ font-size: 13px; opacity: 0.85; margin-top: 4px; }}
  .cover .generated {{ font-size: 11px; opacity: 0.6; margin-top: 10px; }}
  h2 {{
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: {COLOR_ACCENT};
    border-bottom: 2px solid {COLOR_ACCENT};
    padding-bottom: 4px;
    margin-top: 24px;
  }}
  .callout {{
    background: #FEF3C7;
    border-left: 4px solid {COLOR_ACCENT};
    padding: 8px 12px;
    font-size: 12px;
    margin: 10px 0;
  }}
  .note {{ color: #B45309; font-size: 12px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    page-break-inside: auto;
  }}
  tr {{ page-break-inside: avoid; }}
  thead {{ display: table-header-group; }}
  th {{
    text-align: left;
    background: #F1F5F9;
    color: #475569;
    font-size: 10px;
    text-transform: uppercase;
    padding: 6px 8px;
    border-bottom: 1px solid #CBD5E1;
  }}
  td {{ padding: 5px 8px; border-bottom: 1px solid #E2E8F0; }}
  td.ticker {{ font-weight: 700; }}
  td.num {{ text-align: right; }}
  td.num.up {{ color: #DC2626; font-weight: 600; }}
  td.num.down {{ color: #16A34A; font-weight: 600; }}
  td.num.flat {{ color: #6B7280; }}
  .footer {{ font-size: 10px; color: #94A3B8; margin-top: 20px; }}
</style>
</head>
<body>
  <div class="cover">
    <div class="name">Shorty</div>
    <div class="sub">ASX Short Interest -- full detail -- report {_esc(report_date)}
      {' vs FY-start ' + _esc(baseline_date) if baseline_date else ''}</div>
    <div class="generated">Generated {generated}</div>
  </div>
  {callout_html}
  <h2>Portfolio Holdings -- every ticker</h2>
  {holdings_table_html}
  <h2>Your Watchlists (Wally) -- every ASX ticker, portfolio holdings excluded</h2>
  {watchlist_section_html}
  <div class="footer">
    Source: ASIC daily aggregate short position reports (download.asic.gov.au/short-selling).
    Figures depend on individual short sellers' own reporting and can be revised; ASIC does
    not verify every report. "FY-Start" is the report closest to 1 July for the current
    financial year. "Change" is in percentage points, not a relative change. Not investment
    advice -- verify figures against the source report before acting on any number here.
  </div>
</body>
</html>"""
