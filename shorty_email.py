"""
shorty_email.py -- email body builder for Shorty, the ASIC short-interest
report.

Table-based with inline styles only, same rule every other agent's email
follows (CLAUDE.md "Email HTML constraints"): no <style> blocks, no
class=, no display:flex/grid. Email clients strip <style> and mishandle
flexbox/grid; a plain <table>/<div> with inline styles is the only
reliable way to lay things out across Gmail/Outlook.

Visual language mirrors Bob/Slinger's results card (sgx_email.py
_results_card_html): dark outer panel, white rounded "cards" with a
colored header bar, bold right-aligned values. Rather than one flat
alphabetical table of every portfolio ticker, the email leads with two
curated sections -- the names actually worth a glance -- then a full
sorted reference table underneath so nothing is lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@dataclass
class ShortyRow:
    ticker: str
    company: str
    current_pct: Optional[float]
    current_rank: Optional[int]
    baseline_pct: Optional[float]
    baseline_rank: Optional[int]
    # Set only for a watchlist row (None for a portfolio holding) -- which
    # of Wally's watchlists this ticker came from, shown as a badge on its
    # card so "most shorted in your watchlists" also says where to find it.
    watchlist: Optional[str] = None

    @property
    def change_pp(self) -> Optional[float]:
        if self.current_pct is None or self.baseline_pct is None:
            return None
        return self.current_pct - self.baseline_pct


# --- palette -- mirrors sgx_email.py so Shorty reads as part of the same
# family of digests (Bob/Slinger). ----------------------------------------

COLOR_BG = "#0B1220"
COLOR_TEXT = "#E5E7EB"
COLOR_MOST_SHORTED = "#F59E0B"   # amber -- "pay attention"
COLOR_MOVERS = "#3B82F6"         # blue -- "this changed"
COLOR_WL_MOST_SHORTED = "#A78BFA"   # violet -- watchlist twin of the amber section
COLOR_WL_MOVERS = "#38BDF8"         # sky -- watchlist twin of the blue section
COLOR_CARD = "#FFFFFF"
COLOR_CARD_HEADER = "#111827"
COLOR_LABEL = "#6B7280"
COLOR_VALUE = "#111827"

MOST_SHORTED_TOP_N = 5
MOVERS_TOP_N = 5
SEVERITY_HIGH_PCT = 10.0
SEVERITY_MED_PCT = 5.0


def _severity_colour(pct: Optional[float]) -> str:
    if pct is None:
        return "#D1D5DB"
    if pct >= SEVERITY_HIGH_PCT:
        return "#EF4444"
    if pct >= SEVERITY_MED_PCT:
        return "#F59E0B"
    return "#9CA3AF"


def _change_colour(change: Optional[float]) -> str:
    if change is None or abs(change) < 0.005:
        return "#6B7280"
    # Red = short interest grew (more bearish positioning against the
    # stock), green = it shrank. Deliberately the opposite sense to a
    # share-price cell elsewhere in the codebase -- the two numbers
    # answer different questions.
    return "#DC2626" if change > 0 else "#16A34A"


def _change_text(change: Optional[float]) -> str:
    if change is None:
        return "n/a"
    if abs(change) < 0.005:
        return "0.00pp —"
    arrow = "▲" if change > 0 else "▼"
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.2f}pp {arrow}"


def _section(title: str, colour: str, blocks_html: List[str]) -> str:
    """A tinted header bar + its member blocks. Mirrors sgx_email._section."""
    if not blocks_html:
        return ""
    return (
        "<div style='margin:18px 0'>"
        f"<div style='padding:10px 12px;background:{colour};color:#0B1220;"
        "font-weight:800;border-radius:10px;letter-spacing:0.6px'>"
        f"{_esc(title)}</div>{''.join(blocks_html)}</div>"
    )


def _mini_stat_row(label: str, value_html: str, shade: bool) -> str:
    bg = "#F9FAFB" if shade else COLOR_CARD
    return (
        f"<tr>"
        f"<td style='padding:8px 12px;background:{bg};color:{COLOR_LABEL};"
        f"font-size:12px;border-bottom:1px solid #E5E7EB'>{label}</td>"
        f"<td style='padding:8px 12px;background:{bg};color:{COLOR_VALUE};"
        f"font-size:13px;font-weight:700;text-align:right;"
        f"border-bottom:1px solid #E5E7EB'>{value_html}</td>"
        f"</tr>"
    )


def _card_html(row: ShortyRow) -> str:
    """One rounded white card per highlighted ticker -- same visual family
    as Bob/Slinger's results card (header bar + mini metric table). A
    watchlist row (row.watchlist set) gets both its company name (derived
    from the ASIC report's own Product field, since the watchlist YAMLs
    carry no names) and a small watchlist badge; a portfolio row just gets
    its tickers.yaml name."""
    severity = _severity_colour(row.current_pct)
    current_html = (
        f"{row.current_pct:.2f}%" if row.current_pct is not None else "not reported"
    )
    if row.current_rank:
        current_html += f" <span style='color:{COLOR_LABEL};font-weight:400;font-size:11px'>(#{row.current_rank} on ASX)</span>"
    baseline_html = (
        f"{row.baseline_pct:.2f}%" if row.baseline_pct is not None else "not reported"
    )
    change = row.change_pp
    change_html = (
        f"<span style='color:{_change_colour(change)}'>{_change_text(change)}</span>"
    )

    rows_html = (
        _mini_stat_row("Current short %", current_html, shade=False)
        + _mini_stat_row("FY-start short %", baseline_html, shade=True)
        + _mini_stat_row("Change since FY start", change_html, shade=False)
    )

    subtitle_parts = []
    if row.company:
        subtitle_parts.append(
            f"<span style='font-weight:400;font-size:12px;opacity:0.85'>{_esc(row.company)}</span>"
        )
    if row.watchlist:
        subtitle_parts.append(
            "<span style='display:inline-block;margin-left:6px;padding:1px 7px;"
            "background:#1E3A5F;color:#7DD3FC;font-size:10px;border-radius:9px;"
            f"vertical-align:middle'>{_esc(row.watchlist)}</span>"
        )
    subtitle_html = " ".join(subtitle_parts)

    return (
        f"<div style='margin:10px 0;padding:0;background:{COLOR_CARD};"
        f"border-radius:10px;overflow:hidden;border-left:4px solid {severity};"
        "box-shadow:0 1px 3px rgba(0,0,0,0.2)'>"
        f"<div style='padding:10px 12px;background:{COLOR_CARD_HEADER};color:#FFFFFF'>"
        f"<span style='font-weight:800;font-size:14px'>{_esc(row.ticker)}</span> "
        f"{subtitle_html}"
        "</div>"
        f"<table style='width:100%;border-collapse:collapse;"
        "font-family:-apple-system, Segoe UI, Arial, sans-serif'>"
        f"{rows_html}</table></div>"
    )


def _select_most_shorted(rows: List[ShortyRow], top_n: int = MOST_SHORTED_TOP_N) -> List[ShortyRow]:
    reported = [r for r in rows if r.current_pct is not None]
    return sorted(reported, key=lambda r: r.current_pct, reverse=True)[:top_n]


def _select_movers(rows: List[ShortyRow], top_n: int = MOVERS_TOP_N) -> List[ShortyRow]:
    moved = [r for r in rows if r.change_pp is not None]
    return sorted(moved, key=lambda r: abs(r.change_pp), reverse=True)[:top_n]


def _sort_key(row: ShortyRow):
    # Reported tickers first (highest % first), not-reported ones last
    # (alphabetical) -- never silently drops a ticker, just pushes the
    # uninteresting ones to the bottom of the reference table.
    return (row.current_pct is None, -(row.current_pct or 0), row.ticker)


def _reference_table_html(rows: List[ShortyRow]) -> str:
    ordered = sorted(rows, key=_sort_key)
    body_rows = "".join(
        "<tr>"
        f"<td style='padding:5px 8px;color:{COLOR_TEXT};font-weight:700'>{_esc(r.ticker)}</td>"
        f"<td style='padding:5px 8px;color:#9CA3AF'>{_esc(r.company)[:30]}</td>"
        f"<td style='padding:5px 8px;text-align:right;color:{COLOR_TEXT}'>"
        f"{f'{r.current_pct:.2f}%' if r.current_pct is not None else 'not reported'}</td>"
        f"<td style='padding:5px 8px;text-align:right;color:{COLOR_TEXT}'>"
        f"{f'{r.baseline_pct:.2f}%' if r.baseline_pct is not None else 'not reported'}</td>"
        f"<td style='padding:5px 8px;text-align:right;color:{_change_colour(r.change_pp)}'>"
        f"{_change_text(r.change_pp)}</td>"
        "</tr>"
        for r in ordered
    ) if ordered else (
        "<tr><td colspan='5' style='color:#6B7280;padding:5px 8px'>"
        "No portfolio tickers found in this report.</td></tr>"
    )
    return (
        "<div style='margin-top:14px'>"
        "<div style='font-size:11px;color:#6B7280;text-transform:uppercase;"
        "letter-spacing:0.5px;margin-bottom:6px'>Every portfolio ticker, sorted by current short %</div>"
        "<table style='width:100%;border-collapse:collapse;font-size:12px'>"
        "<tr style='color:#6B7280;font-size:10px;text-align:left'>"
        "<th style='padding:5px 8px;text-align:left'>Ticker</th>"
        "<th style='padding:5px 8px;text-align:left'>Company</th>"
        "<th style='padding:5px 8px;text-align:right'>Current</th>"
        "<th style='padding:5px 8px;text-align:right'>FY-Start</th>"
        "<th style='padding:5px 8px;text-align:right'>Change</th></tr>"
        f"{body_rows}</table></div>"
    )


def build_email(
    report_date: str,
    baseline_date: Optional[str],
    rows: List[ShortyRow],
    top_market_ticker: Optional[str] = None,
    top_market_company: Optional[str] = None,
    top_market_pct: Optional[float] = None,
    baseline_unavailable_note: Optional[str] = None,
    watchlist_rows: Optional[List[ShortyRow]] = None,
    watchlist_unavailable_note: Optional[str] = None,
    pdf_attached: bool = False,
) -> tuple[str, str, str]:
    """Returns (subject, body_text, body_html).

    *watchlist_rows* are tickers from Wally's watchlists (portfolio
    holdings already excluded by the caller) -- rendered as their own
    "most shorted" / "biggest movers" card sections below the holdings
    ones, same curation logic, just a second universe. *pdf_attached*
    adds a footer line pointing at the attached full-detail PDF, which
    carries every ticker from both universes (the email only ever shows
    the curated top few)."""
    subject = f"Shorty — ASX Short Interest — {report_date}"
    watchlist_rows = watchlist_rows or []

    most_shorted = _select_most_shorted(rows)
    movers = _select_movers(rows) if not baseline_unavailable_note else []
    wl_most_shorted = _select_most_shorted(watchlist_rows) if not watchlist_unavailable_note else []
    wl_movers = (
        _select_movers(watchlist_rows)
        if watchlist_rows and not baseline_unavailable_note and not watchlist_unavailable_note
        else []
    )

    callout_html = ""
    if top_market_ticker:
        callout_html = (
            "<p style='margin:10px 0;color:#CBD5E1;font-size:13px'>Most shorted stock on the ASX today: "
            f"<strong style='color:#FBBF24'>{_esc(top_market_ticker)}</strong> "
            f"({_esc(top_market_company or '')}) at <strong>{top_market_pct:.2f}%</strong>.</p>"
        )

    baseline_note_html = ""
    if baseline_unavailable_note:
        baseline_note_html = (
            f"<p style='color:#F59E0B;font-size:12px'>{_esc(baseline_unavailable_note)}</p>"
        )

    most_shorted_html = _section(
        f"MOST SHORTED IN YOUR PORTFOLIO (TOP {len(most_shorted)})" if most_shorted else "MOST SHORTED IN YOUR PORTFOLIO",
        COLOR_MOST_SHORTED,
        [_card_html(r) for r in most_shorted],
    ) if most_shorted else (
        "<p style='color:#9CA3AF;font-size:13px'>No portfolio ticker had a reported short position.</p>"
    )

    movers_html = _section(
        f"BIGGEST MOVERS SINCE FY START (TOP {len(movers)})" if movers else "BIGGEST MOVERS SINCE FY START",
        COLOR_MOVERS,
        [_card_html(r) for r in movers],
    ) if movers else ""

    watchlist_note_html = ""
    watchlist_divider_html = ""
    wl_most_shorted_html = ""
    wl_movers_html = ""
    if watchlist_unavailable_note:
        watchlist_divider_html = (
            "<div style='margin:22px 0 4px 0;font-size:12px;color:#64748B;"
            "text-transform:uppercase;letter-spacing:0.6px;border-top:1px solid #1E293B;"
            "padding-top:14px'>Your watchlists (Wally)</div>"
        )
        watchlist_note_html = f"<p style='color:#F59E0B;font-size:12px'>{_esc(watchlist_unavailable_note)}</p>"
    elif watchlist_rows:
        watchlist_divider_html = (
            "<div style='margin:22px 0 4px 0;font-size:12px;color:#64748B;"
            "text-transform:uppercase;letter-spacing:0.6px;border-top:1px solid #1E293B;"
            "padding-top:14px'>Your watchlists (Wally)</div>"
        )
        wl_most_shorted_html = _section(
            f"MOST SHORTED IN YOUR WATCHLISTS (TOP {len(wl_most_shorted)})" if wl_most_shorted else "MOST SHORTED IN YOUR WATCHLISTS",
            COLOR_WL_MOST_SHORTED,
            [_card_html(r) for r in wl_most_shorted],
        ) if wl_most_shorted else (
            "<p style='color:#9CA3AF;font-size:13px'>No watchlist ticker had a reported short position.</p>"
        )
        wl_movers_html = _section(
            f"BIGGEST MOVERS IN YOUR WATCHLISTS (TOP {len(wl_movers)})" if wl_movers else "BIGGEST MOVERS IN YOUR WATCHLISTS",
            COLOR_WL_MOVERS,
            [_card_html(r) for r in wl_movers],
        ) if wl_movers else ""

    pdf_note_html = ""
    if pdf_attached:
        pdf_note_html = (
            "<p style='font-size:12px;color:#9CA3AF;font-style:italic;margin-top:14px'>"
            "Full detail -- every portfolio holding and every watchlist ticker, sorted -- "
            "is attached as a PDF.</p>"
        )

    footer_note_html = (
        "<p style='font-size:11px;color:#6b7280;margin-top:14px'>"
        "Source: ASIC daily aggregate short position reports "
        "(download.asic.gov.au/short-selling). Figures depend on individual "
        "short sellers' own reporting and can be revised; ASIC does not "
        "verify every report. \"FY-Start\" is the report closest to 1 July "
        "for the current financial year. \"Change\" is in percentage "
        "points, not a relative change.</p>"
    )

    header_html = (
        f"<div style='padding:18px;background:{COLOR_BG};color:{COLOR_TEXT};"
        "font-family:-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif;'>"
        "<div style='font-size:22px;font-weight:900;margin-bottom:6px'>Shorty</div>"
        f"<div style='opacity:0.9;font-size:14px;margin-bottom:10px'>"
        f"ASX Short Interest — report {_esc(report_date)}"
        f"{' vs FY-start ' + _esc(baseline_date) if baseline_date else ''}</div>"
        "</div>"
    )

    body_html = (
        header_html
        + "<div style='padding:0 18px 18px 18px;font-family:-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif;'>"
        + callout_html + baseline_note_html
        + most_shorted_html + movers_html
        + _reference_table_html(rows)
        + watchlist_divider_html + watchlist_note_html
        + wl_most_shorted_html + wl_movers_html
        + pdf_note_html
        + footer_note_html
        + "</div>"
    )

    ordered = sorted(rows, key=_sort_key)
    lines = [
        "Shorty — ASX Short Interest",
        f"Report date: {report_date}" + (f" | FY-start baseline: {baseline_date}" if baseline_date else ""),
        "",
    ]
    if top_market_ticker:
        lines.append(f"Most shorted on ASX: {top_market_ticker} ({top_market_company}) at {top_market_pct:.2f}%")
        lines.append("")
    if baseline_unavailable_note:
        lines.append(baseline_unavailable_note)
        lines.append("")
    if most_shorted:
        lines.append(f"MOST SHORTED IN YOUR PORTFOLIO (top {len(most_shorted)}):")
        for r in most_shorted:
            rank = f" (#{r.current_rank} on ASX)" if r.current_rank else ""
            lines.append(f"  {r.ticker:<6}{r.company[:28]:<30}{r.current_pct:.2f}%{rank}")
        lines.append("")
    if movers:
        lines.append(f"BIGGEST MOVERS SINCE FY START (top {len(movers)}):")
        for r in movers:
            lines.append(f"  {r.ticker:<6}{r.company[:28]:<30}{_change_text(r.change_pp)}")
        lines.append("")
    lines.append(f"{'Ticker':<8}{'Company':<32}{'Current':<14}{'FY-Start':<14}{'Change':<12}")
    for r in ordered:
        cur = f"{r.current_pct:.2f}%" if r.current_pct is not None else "not reported"
        base = f"{r.baseline_pct:.2f}%" if r.baseline_pct is not None else "not reported"
        lines.append(f"{r.ticker:<8}{r.company[:30]:<32}{cur:<14}{base:<14}{_change_text(r.change_pp):<12}")
    lines.append("")

    if watchlist_unavailable_note:
        lines.append("YOUR WATCHLISTS (WALLY):")
        lines.append(watchlist_unavailable_note)
        lines.append("")
    elif watchlist_rows:
        lines.append("YOUR WATCHLISTS (WALLY):")
        if wl_most_shorted:
            lines.append(f"MOST SHORTED IN YOUR WATCHLISTS (top {len(wl_most_shorted)}):")
            for r in wl_most_shorted:
                rank = f" (#{r.current_rank} on ASX)" if r.current_rank else ""
                lines.append(f"  {r.ticker:<6}{r.watchlist or '':<24}{r.current_pct:.2f}%{rank}")
            lines.append("")
        if wl_movers:
            lines.append(f"BIGGEST MOVERS IN YOUR WATCHLISTS (top {len(wl_movers)}):")
            for r in wl_movers:
                lines.append(f"  {r.ticker:<6}{r.watchlist or '':<24}{_change_text(r.change_pp)}")
            lines.append("")

    if pdf_attached:
        lines.append("Full detail -- every holding and every watchlist ticker, sorted -- is attached as a PDF.")
        lines.append("")
    lines.append("Source: ASIC daily aggregate short position reports (download.asic.gov.au/short-selling).")
    body_text = "\n".join(lines)

    return subject, body_text, body_html


def build_failure_email(reason: str) -> tuple[str, str, str]:
    subject = "Shorty — ASX Short Interest — fetch failed"
    body_text = (
        "Shorty could not fetch an ASIC short position report this run.\n\n"
        f"Reason: {reason}\n\n"
        "Check https://www.asic.gov.au/regulatory-resources/markets/short-selling/"
        "short-position-reports-table manually."
    )
    body_html = (
        f"<div style='padding:18px;background:{COLOR_BG};color:{COLOR_TEXT};"
        "font-family:-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif;'>"
        "<div style='font-size:22px;font-weight:900;margin-bottom:6px'>Shorty</div>"
        "<div style='color:#ef4444;font-weight:bold;margin-bottom:10px'>FETCH FAILED</div>"
        f"<p>{_esc(reason)}</p>"
        "<p>Check the ASIC short position reports table manually: "
        "https://www.asic.gov.au/regulatory-resources/markets/short-selling/"
        "short-position-reports-table</p>"
        "</div>"
    )
    return subject, body_text, body_html
