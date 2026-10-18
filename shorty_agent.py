"""
shorty_agent.py -- Shorty orchestrator: ASIC short-interest digest.

Pipeline
--------
    1. Find the most recent available ASIC short position report (probe
       backward from today -- ASIC publishes with a lag, so today's/
       yesterday's report often doesn't exist yet).
    2. Find the report closest to 1 July of the current financial year
       (probe outward from that date in both directions).
    3. For every ASX ticker in the portfolio (tickers.yaml, ETFs excluded),
       look up its % of shares on issue reported short in both reports,
       plus its market-wide rank. Same lookup for every ASX ticker across
       Wally's five watchlists, minus whatever's already a holding.
    4. Email a curated glance for both universes (most shorted, biggest
       movers) with a full-detail PDF attached -- the watchlist universe
       alone can run past 150 tickers, too long for the email body.
    5. Write docs/data/shorty.json for the dashboard (portfolio holdings
       only -- the watchlist breakdown lives in the email/PDF, not yet on
       the dashboard).

No LLM call, no seen-state dedup -- this is a plain scheduled numbers
report, not an event-driven digest, so it emails on every run regardless
of whether anything changed (same as Wally's weekly screen).

CLI
---
    python shorty_agent.py [--dry-run] [--report-date YYYY-MM-DD] [--baseline-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from shorty_fetch import (
    AsicFetchError,
    ShortRow,
    clean_product_name,
    find_most_recent_report,
    find_nearest_report,
    fetch_report,
    fy_start_date,
    load_portfolio_tickers,
    load_watchlist_universe,
    rank_map,
    rows_by_code,
    sydney_today,
)
from shorty_email import ShortyRow, build_email, build_failure_email
from shorty_pdf import build_full_report_pdf_html
from shared.email_service import send_email as shared_send_email

SHORTY_NAME = "Shorty"
SHORTY_DASHBOARD_JSON = Path(__file__).resolve().parent / "docs" / "data" / "shorty.json"

MOST_RECENT_MAX_BACK_DAYS = 20
BASELINE_MAX_RADIUS_DAYS = 14


def _log(msg: str) -> None:
    print(msg, flush=True)


def _top_market(rows: List[ShortRow]) -> Optional[ShortRow]:
    if not rows:
        return None
    return max(rows, key=lambda r: r.pct_short)


def _build_rows(
    tickers: Dict[str, str],
    current_by_code: Dict[str, ShortRow],
    current_rank: Dict[str, int],
    baseline_by_code: Dict[str, ShortRow],
    baseline_rank: Dict[str, int],
) -> List[ShortyRow]:
    out: List[ShortyRow] = []
    for ticker in sorted(tickers):
        company = tickers[ticker]
        cur = current_by_code.get(ticker)
        base = baseline_by_code.get(ticker)
        out.append(ShortyRow(
            ticker=ticker,
            company=company,
            current_pct=cur.pct_short if cur else None,
            current_rank=current_rank.get(ticker),
            baseline_pct=base.pct_short if base else None,
            baseline_rank=baseline_rank.get(ticker),
        ))
    return out


def _build_watchlist_rows(
    universe: Dict[str, str],
    current_by_code: Dict[str, ShortRow],
    current_rank: Dict[str, int],
    baseline_by_code: Dict[str, ShortRow],
    baseline_rank: Dict[str, int],
) -> List[ShortyRow]:
    """Same shape as _build_rows, but keyed by Wally's watchlist universe
    (ticker -> watchlist name) rather than the portfolio (ticker -> company
    name). The watchlist YAMLs carry no company names, so `company` is
    filled from the ASIC report's own Product field (cleaned up) when the
    ticker was found there -- which it always is for any row that ends up
    on a "most shorted" or "movers" card, since selection for those cards
    requires current_pct (and, for movers, baseline_pct) to be set. A
    ticker that appears in neither report simply has no name available,
    same as it has no percentage."""
    out: List[ShortyRow] = []
    for ticker in sorted(universe):
        cur = current_by_code.get(ticker)
        base = baseline_by_code.get(ticker)
        company = clean_product_name((cur or base).product) if (cur or base) else ""
        out.append(ShortyRow(
            ticker=ticker,
            company=company,
            current_pct=cur.pct_short if cur else None,
            current_rank=current_rank.get(ticker),
            baseline_pct=base.pct_short if base else None,
            baseline_rank=baseline_rank.get(ticker),
            watchlist=universe[ticker],
        ))
    return out


def _render_pdf(html: str, out_path: Path) -> bool:
    """Print *html* to *out_path* via Playwright's bundled Chromium.
    ubuntu-latest has no fingerprint constraint on rendering (unlike
    SGX), so the bundled browser is enough -- same reasoning as Bob USA's
    _render_analysis_pdf. prefer_css_page_size + no imperative margin
    lets the HTML's own @page rule (and its page-number footer) win,
    same choice Ned's transcript PDF renderer makes for a multi-page
    document."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        _log(f"[pdf] playwright not available: {exc}")
        return False
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load")
                page.pdf(path=str(out_path), print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
        _log(f"[pdf] wrote {out_path.name} ({out_path.stat().st_size}B)")
        return True
    except Exception as exc:
        _log(f"[pdf] render failed: {exc.__class__.__name__}: {exc}")
        return False


def _dashboard_payload(
    report_date: dt.date,
    baseline_date: Optional[dt.date],
    rows: List[ShortyRow],
    top_market: Optional[ShortRow],
    baseline_unavailable_note: Optional[str],
    watchlist_count: int = 0,
    watchlist_unavailable_note: Optional[str] = None,
) -> Dict:
    return {
        "last_run": sydney_today().isoformat(),
        "report_date": report_date.isoformat(),
        "baseline_date": baseline_date.isoformat() if baseline_date else None,
        "baseline_unavailable_note": baseline_unavailable_note,
        # Watchlist tickers aren't rendered on the dashboard yet -- the
        # count + any error is recorded here so a future dashboard pass
        # has somewhere to read it from, and so a watchlist-load failure
        # is visible in the JSON rather than only in the Actions log.
        "watchlist_count": watchlist_count,
        "watchlist_unavailable_note": watchlist_unavailable_note,
        "top_market": (
            {"ticker": top_market.product_code, "company": top_market.product, "pct": top_market.pct_short}
            if top_market else None
        ),
        "rows": [
            {
                "ticker": r.ticker,
                "company": r.company,
                "current_pct": r.current_pct,
                "current_rank": r.current_rank,
                "baseline_pct": r.baseline_pct,
                "baseline_rank": r.baseline_rank,
                "change_pp": r.change_pp,
            }
            for r in rows
        ],
    }


def _write_dashboard_json(payload: Dict) -> None:
    try:
        SHORTY_DASHBOARD_JSON.parent.mkdir(parents=True, exist_ok=True)
        SHORTY_DASHBOARD_JSON.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        _log(f"[main] dashboard JSON written -> {SHORTY_DASHBOARD_JSON}")
    except Exception as exc:
        _log(f"[main] dashboard JSON write failed: {exc.__class__.__name__}: {exc}")


def _send_email(
    subject: str, body_text: str, body_html: str,
    attachments: Optional[List[Path]] = None,
) -> bool:
    return shared_send_email(
        subject, body_text, body_html,
        attachments=attachments,
        force_type=("application", "pdf"),
        raise_on_error=False, log_details=True, log=_log, log_prefix="[email]",
    )


def run(
    dry_run: bool = False,
    report_date_override: Optional[str] = None,
    baseline_date_override: Optional[str] = None,
) -> int:
    today = sydney_today()
    _log(f"{SHORTY_NAME} -- run date {today.isoformat()} dry_run={dry_run}")

    # 1. Most recent report.
    if report_date_override:
        d = dt.date.fromisoformat(report_date_override)
        try:
            rows = fetch_report(d, log=_log)
        except AsicFetchError as exc:
            _log(f"[main] FATAL: {exc}")
            return 2
        report_date, report_rows = (d, rows) if rows is not None else (None, None)
    else:
        try:
            report_date, report_rows = find_most_recent_report(
                today, max_back_days=MOST_RECENT_MAX_BACK_DAYS, log=_log,
            )
        except AsicFetchError as exc:
            _log(f"[main] FATAL: {exc}")
            report_date, report_rows = None, None

    if report_date is None or report_rows is None:
        reason = (
            f"No ASIC short position report found in the last "
            f"{MOST_RECENT_MAX_BACK_DAYS} days (searched back from {today.isoformat()})."
        )
        _log(f"[main] {reason}")
        subject, body_text, body_html = build_failure_email(reason)
        if not dry_run:
            _send_email(subject, body_text, body_html)
        else:
            _log("[main] DRY RUN -- failure email not sent")
        return 1

    # 2. FY-start baseline.
    fy_start = fy_start_date(today)
    baseline_unavailable_note: Optional[str] = None
    if baseline_date_override:
        bd = dt.date.fromisoformat(baseline_date_override)
        try:
            baseline_rows = fetch_report(bd, log=_log)
        except AsicFetchError as exc:
            _log(f"[main] baseline fetch error: {exc}")
            baseline_rows = None
        baseline_date = bd if baseline_rows is not None else None
    else:
        try:
            baseline_date, baseline_rows = find_nearest_report(
                fy_start, max_radius_days=BASELINE_MAX_RADIUS_DAYS, log=_log,
            )
        except AsicFetchError as exc:
            _log(f"[main] baseline fetch error: {exc}")
            baseline_date, baseline_rows = None, None

    if baseline_date is None or baseline_rows is None:
        baseline_unavailable_note = (
            f"FY-start baseline unavailable: no report found within "
            f"{BASELINE_MAX_RADIUS_DAYS} days of {fy_start.isoformat()}."
        )
        _log(f"[main] {baseline_unavailable_note}")
        baseline_rows = []

    # 3. Portfolio tickers + lookups.
    tickers = load_portfolio_tickers()
    if not tickers:
        _log("[main] no ASX tickers found in tickers.yaml (after excluding ETFs) -- nothing to report")

    current_by_code = rows_by_code(report_rows)
    current_rank = rank_map(report_rows)
    baseline_by_code = rows_by_code(baseline_rows) if baseline_rows else {}
    baseline_rank = rank_map(baseline_rows) if baseline_rows else {}

    rows = _build_rows(tickers, current_by_code, current_rank, baseline_by_code, baseline_rank)
    top_market = _top_market(report_rows)

    # 3b. Watchlist universe (Wally's five standard lists, ASX-only,
    # portfolio holdings excluded since they already have their own
    # section). A load failure degrades to "holdings only" with a
    # visible note, never a silently empty section.
    watchlist_universe, watchlist_error = load_watchlist_universe(
        exclude=set(tickers.keys()), log=_log,
    )
    watchlist_rows = _build_watchlist_rows(
        watchlist_universe, current_by_code, current_rank, baseline_by_code, baseline_rank,
    )

    # 4. Full-detail PDF (every holding, every watchlist ticker) -- the
    # watchlist universe alone can run past 150 tickers, too long for
    # the email body, so the email only ever shows the curated top few
    # and this PDF carries everything.
    with tempfile.TemporaryDirectory(prefix="shorty_pdf_") as tmp:
        pdf_path = Path(tmp) / f"shorty_{report_date.isoformat()}.pdf"
        pdf_html = build_full_report_pdf_html(
            report_date=report_date.isoformat(),
            baseline_date=baseline_date.isoformat() if baseline_date else None,
            holdings_rows=rows,
            watchlist_rows=watchlist_rows,
            top_market_ticker=top_market.product_code if top_market else None,
            top_market_company=top_market.product if top_market else None,
            top_market_pct=top_market.pct_short if top_market else None,
            watchlist_unavailable_note=watchlist_error,
        )
        pdf_ok = _render_pdf(pdf_html, pdf_path)
        attachment = pdf_path if pdf_ok else None

        # 5. Email.
        subject, body_text, body_html = build_email(
            report_date=report_date.isoformat(),
            baseline_date=baseline_date.isoformat() if baseline_date else None,
            rows=rows,
            top_market_ticker=top_market.product_code if top_market else None,
            top_market_company=top_market.product if top_market else None,
            top_market_pct=top_market.pct_short if top_market else None,
            baseline_unavailable_note=baseline_unavailable_note,
            watchlist_rows=watchlist_rows,
            watchlist_unavailable_note=watchlist_error,
            pdf_attached=attachment is not None,
        )

        if dry_run:
            out_dir = Path("outputs/shorty")
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "digest_preview.html").write_text(body_html, encoding="utf-8")
            (out_dir / "digest_preview.txt").write_text(body_text, encoding="utf-8")
            if attachment:
                dest = out_dir / attachment.name
                dest.write_bytes(attachment.read_bytes())
                _log(f"[main] DRY RUN -- copied PDF -> {dest}")
            _log(f"[main] DRY RUN -- wrote preview to {out_dir}/digest_preview.*")
        else:
            _send_email(subject, body_text, body_html, attachments=[attachment] if attachment else None)

    # 6. Dashboard JSON (written on dry run too, same convention Bob USA uses).
    payload = _dashboard_payload(
        report_date, baseline_date, rows, top_market, baseline_unavailable_note,
        watchlist_count=len(watchlist_rows), watchlist_unavailable_note=watchlist_error,
    )
    _write_dashboard_json(payload)

    return 0


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Shorty -- ASIC short-interest digest.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build digest + preview but don't send email.")
    parser.add_argument("--report-date", default=None,
                        help="Override: use exactly this date's report instead of probing "
                             "for the most recent one (YYYY-MM-DD).")
    parser.add_argument("--baseline-date", default=None,
                        help="Override: use exactly this date's report as the FY-start "
                             "baseline instead of probing near 1 July (YYYY-MM-DD).")
    args = parser.parse_args()
    try:
        return run(
            dry_run=args.dry_run,
            report_date_override=args.report_date,
            baseline_date_override=args.baseline_date,
        )
    except Exception as exc:
        _log(f"[main] FATAL {exc.__class__.__name__}: {exc}")
        _log(traceback.format_exc())
        return 2


if __name__ == "__main__":
    sys.exit(_cli())
