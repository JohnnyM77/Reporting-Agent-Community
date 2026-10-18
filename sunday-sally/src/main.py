from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .alert_engine import ON_DEMAND_TIER, AlertClassification, apply_harry_flag, classify_alert, sally_verdict
from .harry_flags import load_harry_flags
from .chatgpt_handoff_builder import build_handoff_payload, save_handoff_payload
from .claude_analyst import analyse_company
from .document_fetcher import fetch_asx_announcements, save_source_documents
from .email_sender import send_summary_email
from .historical_multiple_analyzer import percentile_bucket, summarize_history, valuation_ratio
from .memo_generator import build_memo_text, save_memo
from .news_context_fetcher import fetch_news_context
from .pathing import ensure_repo_root_on_path, repo_root, resolve_output_root
from .portfolio_loader import PortfolioCompany, load_portfolio
from .price_monitor import fetch_price_data
from .run_logger import write_run_log
from .valuation_engine import fetch_valuation_snapshot
from .value_wedge import (
    WedgeConfigMissing, compute_wedge, forecast_lines, iter_tickers, low_line, load_wedge_inputs, normalise_ticker, write_outputs,
)
from .wedge_chart import render_wedge_chart
from .wedge_report import wedge_html, wedge_markdown
from .wedge_workbook import build_wedge_workbook
from .weekly_scheduler import run_window_info

# Value chart builder lives in the wally package at repo root
ensure_repo_root_on_path()

from shared.range_chart import range_chart_html, render_range_chart  # noqa: E402
from shared.ranges import compact as _compact_ranges  # noqa: E402
from shared.ranges import range_bar_html, range_payload  # noqa: E402
_build_value_chart = None
_drive_upload = None
_VALUE_CHART_AVAILABLE = False
try:
    from wally.value_chart_builder import build_value_chart as _build_value_chart
    _VALUE_CHART_AVAILABLE = True
except ImportError:
    pass
try:
    from wally.drive_upload import upload_or_replace_xlsx as _drive_upload
except ImportError:
    pass
fetch_significant_news = None
build_news_html = None
NewsItem = None
NEWS_LOOKBACK_DAYS = 90
_ASX_NEWS_AVAILABLE = False
try:
    from wally.asx_news import fetch_significant_news, NewsItem
    from wally.email_report import build_news_html
    from wally.config import NEWS_LOOKBACK_DAYS
    _ASX_NEWS_AVAILABLE = True
except ImportError:
    pass


def _load_settings() -> dict:
    cfg_path = os.environ.get("SALLY_CONFIG_PATH", "config/settings.yaml")
    return yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}


def _run_folder(base_output_root: str, timezone: str, label: str = "Weekly Review") -> Path:
    now_local = dt.datetime.now(ZoneInfo(timezone))
    # resolve_output_root anchors to sunday-sally/ regardless of CWD
    return (
        resolve_output_root(base_output_root)
        / str(now_local.year)
        / f"{now_local.date().isoformat()} {label}"
    )


_WEDGE_MISSING: dict[str, str] = {}   # ticker -> why there is no wedge (shown in the email, not a blank)


def _build_wedge(company, near_high_max: float, company_name: str | None = None):
    """The BUY/SELL value wedge for one company, or None (never fatal)."""
    try:
        inputs = load_wedge_inputs(company.exchange_ticker, repo=repo_root(), company_name=company_name,
                                   start=os.environ.get("SALLY_WEDGE_START") or None)
        result = compute_wedge(inputs, near_high_threshold=near_high_max)
        print(f"[sally] wedge {result.headline}")
        for e in result.events:
            print(f"[sally]   {e.date:%Y-%m-%d} {e.kind}: {e.text}")
        for q, ans in result.diagnostics:
            print(f"[sally]   Q: {q}\n[sally]      {ans}")
        for w in result.inputs.warnings:
            print(f"[sally]   note: {w}")
        for f in forecast_lines(result):
            print(f"[sally]   forecast: {f}")
        if low_line(result):
            print(f"[sally]   {low_line(result)}")
        return result
    except WedgeConfigMissing as exc:
        print(f"[sally] no wedge for {company.ticker}: {exc}")
        _WEDGE_MISSING[company.ticker] = _short_reason(str(exc))
    except Exception as exc:
        print(f"[sally] wedge failed for {company.ticker}: {exc}")
        _WEDGE_MISSING[company.ticker] = f"wedge failed: {type(exc).__name__}"
    return None


def _short_reason(msg: str) -> str:
    """'no wedge for X: loss-making (...)' -> 'no wedge: loss-making' for the table."""
    import re
    low = msg.lower()
    m = re.search(r": (.+?) archetype has no P/E line", msg)
    if m:
        return f"no wedge: {m.group(1)} archetype" + (" (unconfirmed)" if "not confirmed" in low else "")
    for key, short in (("pre-profit", "no wedge: pre-profit"), ("no p/e line", "no wedge: not valued on P/E"),
                       ("loss-making", "no wedge: loss-making"), ("no usable annual eps", "no wedge: no EPS data"),
                       ("not on the eodhd plan", "no wedge: exchange not covered")):
        if key in low:
            return short
    return "no wedge: " + (msg.split(":", 1)[-1].strip()[:60] if ":" in msg else msg[:60])


def _wedge_fields(result) -> dict:
    cur = result.current if result else None
    if cur is None or cur.position is None:
        return {"wedge_zone": None, "wedge_position": None, "wedge_headline": result.headline if result else None}
    return {
        "wedge_zone": cur.zone,
        "wedge_position": round(cur.position, 4),
        "wedge_headline": result.headline,
        "wedge_buy_value": round(cur.buy_value, 4),
        "wedge_sell_value": round(cur.sell_value, 4),
        "wedge_fair_value": round(cur.fair_value, 4) if cur.fair_value else None,
        "wedge_buy_pe": cur.buy_pe,
        "wedge_sell_pe": cur.sell_pe,
        "wedge_actual_pe": round(cur.actual_pe, 2) if cur.actual_pe else None,
        "wedge_eps_cents": cur.eps_used,
        "wedge_eps_period": cur.period,
        "wedge_eps_basis": result.inputs.eps_basis_label,
        "wedge_rel_width": cur.rel_wedge,
        "wedge_diagnostics": [{"question": q, "answer": a} for q, a in result.diagnostics],
        "wedge_forecast": forecast_lines(result),
        "wedge_low_line": low_line(result),
        "wedge_outlook": result.inputs.outlook or None,
        "wedge_forecast_label": result.inputs.forecast_label,
    }


def _process_company(company, settings, run_folder, tz, near_high_max, thresholds,
                     harry_flag: dict | None = None, force: bool = False) -> dict | None:
    """
    Run the full valuation pipeline for one company.
    Returns a summary dict if flagged (or ``force``), else None.
    One bad ticker never kills the whole run — wrap calls in try/except in main().
    """
    price = fetch_price_data(company.exchange_ticker, company.ticker)
    if not price:
        return None

    wedge = _build_wedge(company, near_high_max, company_name=price.company_name)
    wedge_now = wedge.current if wedge else None

    val = fetch_valuation_snapshot(company.exchange_ticker)
    hist = summarize_history(company.exchange_ticker, val.trailing_pe, val.ev_to_ebitda)

    pe_3_ratio = valuation_ratio(val.trailing_pe, hist.pe_3y_avg)
    pe_5_ratio = valuation_ratio(val.trailing_pe, hist.pe_5y_avg)
    pe_10_ratio = valuation_ratio(val.trailing_pe, hist.pe_10y_avg)

    evidence_strength = 0.6 if (val.fcf_yield and val.fcf_yield > 0.03) else 0.35
    alert = classify_alert(
        distance_to_high=price.distance_to_high,
        threshold=near_high_max,
        pe_ratio_3y=pe_3_ratio,
        pe_ratio_5y=pe_5_ratio,
        pe_ratio_10y=pe_10_ratio,
        valuation_percentile=hist.valuation_percentile,
        evidence_strength=evidence_strength,
        review_ratio=float(thresholds.get("review_ratio", 1.15)),
        deep_ratio=float(thresholds.get("deep_review_ratio", 1.35)),
        wedge=(
            {"position": wedge_now.position, "actual_pe": wedge_now.actual_pe,
             "sell_pe": wedge_now.sell_pe, "sell_value": wedge_now.sell_value}
            if wedge_now and wedge_now.position is not None else None
        ),
    )

    alert = apply_harry_flag(alert, harry_flag)
    if force and not alert.triggered:
        alert = AlertClassification(triggered=True, tier=ON_DEMAND_TIER,
                                    reasons=["on-demand wedge check (no trigger fired)"])
    if not alert.triggered:
        return None

    announcements = fetch_asx_announcements(company.ticker)
    news = fetch_news_context(company.exchange_ticker)
    save_source_documents(company.ticker, run_folder, announcements)

    # Significant ASX announcements over the last N days (same significance
    # taxonomy Wally uses for his flagged tickers — trading halts, capital
    # raisings, M&A, guidance, results, board changes, etc).
    significant_news = fetch_significant_news(company.exchange_ticker) if _ASX_NEWS_AVAILABLE else None
    significant_news_dicts = [item.to_dict() for item in (significant_news or [])]

    summary = {
        "company_name": price.company_name,
        "ticker": company.ticker,
        "review_date": dt.datetime.now(ZoneInfo(tz)).date().isoformat(),
        "current_price": price.current_price,
        "high_52w": price.high_52w,
        "distance_to_high_pct": round(price.distance_to_high * 100, 2),
        "market_cap": price.market_cap,
        "trailing_pe": val.trailing_pe,
        "forward_pe": val.forward_pe,
        "ev_ebitda": val.ev_to_ebitda,
        "price_to_sales": val.price_to_sales,
        "fcf_yield": val.fcf_yield,
        "dividend_yield": val.dividend_yield,
        "pe_3y_avg": hist.pe_3y_avg,
        "pe_5y_avg": hist.pe_5y_avg,
        "pe_10y_avg": hist.pe_10y_avg,
        "valuation_percentile": hist.valuation_percentile,
        "valuation_percentile_bucket": percentile_bucket(hist.valuation_percentile),
        "significant_news": significant_news_dicts,
        "significant_news_lookback_days": NEWS_LOOKBACK_DAYS,
        "alert_tier": alert.tier,
        "sally_verdict": sally_verdict(alert),
        "harry_flag": harry_flag if alert.harry_flag else None,
        **_wedge_fields(wedge),
        "wedge_missing": None if wedge is not None else _WEDGE_MISSING.get(company.ticker, "no wedge"),
    }

    handoff = build_handoff_payload(
        company={"ticker": company.ticker, "company_name": price.company_name},
        valuation=summary,
        history={"notes": hist.notes},
        announcements=announcements,
        news=news,
        run_date=summary["review_date"],
        significant_news=significant_news_dicts,
    )

    ticker_folder = run_folder / company.ticker
    if wedge is not None:
        write_outputs(wedge, ticker_folder)
        png = render_wedge_chart(wedge, ticker_folder / "wedge_chart.png")
        try:
            build_wedge_workbook(wedge, ticker_folder / "value_wedge.xlsx")
        except Exception as exc:
            print(f"[sally] wedge workbook failed for {company.ticker}: {exc}")
        summary["wedge_html"] = wedge_html(wedge, cid=f"wedge_{company.ticker.lower()}" if png else None)
    save_handoff_payload(ticker_folder / "handoff_payload.json", handoff)

    # 52-week P/E and P/FCF: a small inline chart plus range bars in the table.
    ranges = range_payload(company.exchange_ticker)
    if ranges:
        summary["ranges_52w"] = _compact_ranges(ranges)
        cid = f"ranges_{company.ticker.lower()}"
        if render_range_chart(ranges, ticker_folder / "ranges_52w.png", company.ticker):
            summary["ranges_html"] = range_chart_html(cid, company.ticker, ranges)

    critical_rows = [
        {
            "issue": "Valuation stretch",
            "bull_case": "Quality rerating",
            "bear_case": "Narrative-driven",
            "evidence": "; ".join(alert.reasons),
            "sally_judgment": summary["sally_verdict"],
        },
        {
            "issue": "Cash conversion",
            "bull_case": "FCF improving",
            "bear_case": "Earnings ahead of cash",
            "evidence": f"FCF yield={val.fcf_yield}",
            "sally_judgment": "Verify statutory cash flow",
        },
    ]
    history_rows = [
        {
            "reporting_period": "current",
            "pe": val.trailing_pe,
            "ev_ebitda": val.ev_to_ebitda,
            "notes": "; ".join(hist.notes),
        }
    ]

    news_headlines = [f"{item['date']} — {item['title']}" for item in significant_news_dicts]
    if isinstance(news, list):
        news_headlines += [n.get("title", "") for n in news if n.get("title")]
    claude_analysis = analyse_company(
        ticker=company.ticker,
        company_name=price.company_name,
        summary=summary,
        reasons=alert.reasons,
        news=news_headlines or None,
        harry_flag=harry_flag if alert.harry_flag else None,
    )

    # Build the value chart workbook + PNG (requires a valuations/<ticker>.yaml config).
    if _VALUE_CHART_AVAILABLE:
        try:
            _build_value_chart(
                company.exchange_ticker,
                output_path=str(ticker_folder / "value_chart.xlsx"),
                save_png=False,   # the wedge chart is the picture now
            )
            print(f"[sally] value chart built for {company.ticker}")
        except FileNotFoundError:
            print(f"[sally] WARNING: no valuations config for {company.ticker} — add valuations/{company.ticker.lower()}_ax.yaml to get a chart")
        except Exception as exc:
            print(f"[sally] value chart build failed for {company.ticker}: {exc}")

    memo = build_memo_text(
        company={"ticker": company.ticker, "company_name": price.company_name},
        summary=summary,
        reasons=alert.reasons,
        doubts=hist.notes,
        decision_framing=summary["sally_verdict"],
        claude_analysis=claude_analysis,
        significant_news=significant_news_dicts,
        lookback_days=NEWS_LOOKBACK_DAYS,
    )
    if wedge is not None:
        memo += wedge_markdown(wedge)
    save_memo(ticker_folder / "memo.md", memo)

    return summary


def main() -> None:
    # ── Startup diagnostics ───────────────────────────────────────────────────
    print("[sally] Starting up...")
    from shared.archetype_sync import safe_sync  # keeps config/ticker_archetypes.yaml in step with the watchlists
    safe_sync()
    print(f"[sally] Value chart builder available: {_VALUE_CHART_AVAILABLE}")
    print(f"[sally] Drive uploader available: {_drive_upload is not None}")
    _oauth_ok = all([
        os.environ.get("GDRIVE_CLIENT_ID", "").strip(),
        os.environ.get("GDRIVE_CLIENT_SECRET", "").strip(),
        os.environ.get("GDRIVE_REFRESH_TOKEN", "").strip(),
    ])
    _sa_ok = bool(os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip())
    _gfolder_ok = bool(os.environ.get("GDRIVE_FOLDER_ID", "").strip())
    if _oauth_ok:
        print("[sally] Drive auth: OAuth2 user credentials (GDRIVE_CLIENT_ID/SECRET/REFRESH_TOKEN) ✓")
    elif _sa_ok:
        print("[sally] Drive auth: service account (WARNING — will fail on personal Gmail Drive — add OAuth2 secrets instead)")
    else:
        print("[sally] Drive auth: NO credentials set — uploads will be skipped")
    print(f"[sally] GDRIVE_FOLDER_ID set: {_gfolder_ok}")
    _email_ok_pre = all([
        os.environ.get("EMAIL_FROM") or os.environ.get("EMAIL_USER"),
        os.environ.get("EMAIL_TO"),
        os.environ.get("SMTP_PASS") or os.environ.get("EMAIL_APP_PASSWORD"),
    ])
    print(f"[sally] Email credentials present: {_email_ok_pre}")
    if not _email_ok_pre:
        missing = [k for k in ("EMAIL_FROM", "EMAIL_TO", "SMTP_PASS") if not os.environ.get(k)]
        print(f"[sally] WARNING: missing env vars → {missing}")

    settings = _load_settings()
    tz = settings.get("timezone", "Asia/Singapore")
    thresholds = settings.get("thresholds", {})
    near_high_max = float(thresholds.get("near_high_distance_max", 0.05))

    # On-demand mode (sally_wedge.yml): named tickers, every one analysed
    # whether or not a trigger fires. One-off: no dashboard write, no Drive.
    on_demand_raw = os.environ.get("SALLY_TICKERS", "").strip()
    on_demand = bool(on_demand_raw)

    run_folder = _run_folder(
        settings.get("outputs", {}).get("root", "data/outputs"), tz,
        label="Wedge Check" if on_demand else "Weekly Review",
    )
    run_folder.mkdir(parents=True, exist_ok=True)

    if on_demand:
        portfolio = []
        for raw in iter_tickers(on_demand_raw):
            exch = normalise_ticker(raw)
            portfolio.append(PortfolioCompany(ticker=exch.split(".")[0], exchange_ticker=exch))
        print(f"[sally] On-demand wedge check: {', '.join(c.exchange_ticker for c in portfolio)}")
    else:
        tickers_file = repo_root() / "tickers.yaml"
        portfolio = load_portfolio(
            source_file=str(tickers_file),
            source_key="asx",
            exchange_suffix=".AX",
        )

    flagged_rows: list[dict] = []
    skipped_tickers: list[str] = []
    harry_flags = load_harry_flags()
    if harry_flags:
        print(f"[sally] Harry flagged {len(harry_flags)} holding(s) with a broken thesis: {', '.join(sorted(harry_flags))}")

    for company in portfolio:
        try:
            result = _process_company(
                company, settings, run_folder, tz, near_high_max, thresholds,
                harry_flag=harry_flags.get(company.ticker.upper()),
                force=on_demand,
            )
            if result:
                flagged_rows.append(result)
        except Exception as exc:
            print(f"[main] ERROR processing {company.ticker}: {exc}")
            skipped_tickers.append(company.ticker)

    now_local = dt.datetime.now(ZoneInfo(tz))

    # -------------------------------------------------------------------------
    # Build email body
    # -------------------------------------------------------------------------
    title = "Sally Wedge Check" if on_demand else "Selling Sally Weekly Review"
    if flagged_rows:
        lines = [
            f"{title} — {now_local.date().isoformat()}",
            f"{len(flagged_rows)} company/companies "
            + ("checked." if on_demand else "flagged this week."),
            "",
            "Companies:" if on_demand else "Flagged companies:",
        ]
        for row in flagged_rows:
            lines.append(
                f"  {row['ticker']} ({row['alert_tier']}) — "
                f"{row['distance_to_high_pct']}% below 52w high — "
                f"{row['sally_verdict']}"
            )
            rg = row.get("ranges_52w") or {}
            for key, label in (("pe", "P/E"), ("pfcf", "P/FCF")):
                r = rg.get(key)
                if r:
                    lines.append(f"    52w {label} (TTM): {r['current']:.1f}x now, range "
                                 f"{r['low']:.1f}x-{r['high']:.1f}x ({r['position']:.0%} of range)")
            if row.get("wedge_headline"):
                lines.append(f"    Wedge: {row['wedge_headline']}")
            for d in row.get("wedge_diagnostics") or []:
                lines.append(f"    - {d['question']} {d['answer']}")
            if row.get("significant_news"):
                lines.append(
                    f"    {len(row['significant_news'])} significant ASX announcement(s) "
                    f"in last {row.get('significant_news_lookback_days', 90)} days"
                )
        lines += [
            "",
            "Valuation workbooks and review memos are attached.",
            "Each .xlsx has six sheets: Summary, Historical, Comparison,",
            "Implied Expectations, Critical Review, Decision Framework.",
        ]
    else:
        lines = [
            f"{title} — {now_local.date().isoformat()}",
            "No valuation stretch alerts. Nothing near a 52-week high and nothing above its SELL value."
            if not on_demand else "No ticker could be analysed (see skipped list).",
        ]

    if skipped_tickers:
        lines += ["", f"Tickers skipped due to data errors: {', '.join(skipped_tickers)}"]

    # -------------------------------------------------------------------------
    # Build attachments and HTML email body with inline PNG charts
    # -------------------------------------------------------------------------
    attachments: list[tuple[Path, str]] = []
    inline_images: list[tuple[str, Path]] = []   # (content_id, png_path)

    summary_email_path = run_folder / "summary_email.md"
    summary_email_path.write_text("\n".join(lines), encoding="utf-8")

    # Attachments: one PDF for the whole run (cover table, each company's
    # wedge chart and memo) plus each company's Excel workbook. The chart PNGs
    # stay inline in the body; SVG, CSV and the memo files stay in the run
    # artifact.
    for row in flagged_rows:
        ticker = row["ticker"]
        ticker_folder = run_folder / ticker
        ranges_png = ticker_folder / "ranges_52w.png"
        if ranges_png.exists() and row.get("ranges_html"):
            inline_images.append((f"ranges_{ticker.lower()}", ranges_png))
        png = ticker_folder / "wedge_chart.png"
        if png.exists():
            inline_images.append((f"wedge_{ticker.lower()}", png))
    if flagged_rows:
        from .wedge_pdf import build_report_pdf
        pdf_name = ("Sally_wedge_check" if on_demand else "Sally_weekly_review") + f"_{now_local.date().isoformat()}.pdf"
        try:
            pdf_path = build_report_pdf(
                flagged_rows, run_folder, run_folder / pdf_name, title=f"{title} — {now_local.date().isoformat()}",
                subtitle=(f"{len(flagged_rows)} {'company' if len(flagged_rows) == 1 else 'companies'} "
                          f"{'checked' if on_demand else 'flagged'}. Value wedge, 52-week multiples and the "
                          "review memo for each."))
            if pdf_path:
                attachments.append((pdf_path, pdf_name))
        except Exception as exc:
            print(f"[sally] PDF report failed: {exc}")
    for row in flagged_rows:
        xlsx = run_folder / row["ticker"] / "value_wedge.xlsx"
        if xlsx.exists():
            attachments.append((xlsx, f"{row['ticker']}_value_wedge.xlsx"))

    # Build HTML body — summary table + inline chart images for each flagged ticker
    html_parts = [
        f"<h2>{title} — {now_local.date().isoformat()}</h2>",
    ]
    if flagged_rows:
        html_parts.append(
            f"<p><strong>{len(flagged_rows)} company/companies "
            + ("checked." if on_demand else "flagged this week.") + "</strong></p>"
        )
        html_parts.append(
            "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse'>"
            "<tr style='background:#1F2D4E;color:white'>"
            "<th>Ticker</th><th>Alert Tier</th><th>% Below 52w High</th><th>52W P/E</th><th>52W P/FCF</th>"
            "<th>Value wedge</th><th>Verdict</th></tr>"
        )
        for row in flagged_rows:
            pos = row.get("wedge_position")
            wedge_cell = (f"{row.get('wedge_zone')} ({pos:.0%})" if pos is not None
                          else (row.get("wedge_missing") or "no wedge"))
            html_parts.append(
                f"<tr><td><b>{row['ticker']}</b></td><td>{row['alert_tier']}</td>"
                f"<td>{row['distance_to_high_pct']}%</td>"
                f"<td>{range_bar_html((row.get('ranges_52w') or {}).get('pe'), 'pe')}</td>"
                f"<td>{range_bar_html((row.get('ranges_52w') or {}).get('pfcf'), 'pfcf')}</td>"
                f"<td>{wedge_cell}</td><td>{row['sally_verdict']}</td></tr>"
            )
        html_parts.append("</table>")
        for row in flagged_rows:
            ticker = row["ticker"]
            if row.get("ranges_html"):
                html_parts.append(row["ranges_html"])
            if row.get("wedge_html"):
                html_parts.append(row["wedge_html"])
            if _ASX_NEWS_AVAILABLE and build_news_html is not None:
                items = [NewsItem(**d) for d in (row.get("significant_news") or [])]
                html_parts.append(build_news_html(ticker, items))
        html_parts.append(
            "<p style='font-size:12px;color:#52514e'>Attached: one PDF with every company's wedge chart and "
            "review memo, and a <b>value_wedge.xlsx</b> per company (the same chart as a native Excel chart on "
            "live formulas: change a BUY/SELL P/E or an EPS figure and it redraws). The editable SVG and the "
            "weekly CSV are in the run artifact.</p>"
        )
    else:
        html_parts.append(f"<p>{lines[1]}</p>")
    if skipped_tickers:
        html_parts.append(f"<p><em>Tickers skipped due to data errors: {', '.join(skipped_tickers)}</em></p>")
    body_html = "\n".join(html_parts)

    flag_count = len(flagged_rows)
    if on_demand:
        zones = "; ".join(f"{r['ticker']} {r.get('wedge_zone') or 'no wedge'}" for r in flagged_rows)
        subject = f"Sally Wedge Check — {now_local.date().isoformat()} — {zones or 'nothing analysed'}"
    else:
        subject = (
            f"Selling Sally — {now_local.date().isoformat()} — "
            + (f"{flag_count} flagged" if flag_count else "All clear")
        )

    email_ok = send_summary_email(
        subject=subject,
        body_text="\n".join(lines),
        attachments=attachments,
        inline_images=inline_images if inline_images else None,
        body_html=body_html,
    )

    # Upload value chart xlsx files to Google Drive (YYMMDD-TICKER.xlsx naming)
    drive_folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    drive_uploads: list[str] = []
    if drive_folder_id and _drive_upload is not None and not on_demand:
        for row in flagged_rows:
            ticker = row["ticker"]
            chart = run_folder / ticker / "value_chart.xlsx"
            if chart.exists():
                drive_name = f"{now_local.strftime('%y%m%d')}-{ticker}.xlsx"
                try:
                    url = _drive_upload(chart, drive_name, folder_id=drive_folder_id)
                    drive_uploads.append(drive_name)
                    print(f"[sally] Drive → {drive_name}: {url}")
                except Exception as exc:
                    print(f"[sally] Drive upload failed for {ticker}: {exc}")

    run_log = {
        "job_name": settings.get("job_name", "sunday_sally_weekly_review"),
        "schedule": settings.get("schedule", {}),
        "run_window": run_window_info(tz),
        "portfolio_size": len(portfolio),
        "flagged_count": flag_count,
        "flagged_tickers": [r["ticker"] for r in flagged_rows],
        "skipped_tickers": skipped_tickers,
        "attachments_sent": [name for _, name in attachments],
        "outputs_root": str(run_folder),
        "email_sent": email_ok,
        "drive_uploads": drive_uploads,
    }
    write_run_log(run_folder / "run_log.json", run_log)

    if on_demand:
        print("[sally] On-demand run: dashboard (docs/data/sally.json) left untouched")
        print(json.dumps(run_log, indent=2))
        return

    # Write dashboard data — path relative to repo root (sally runs from sunday-sally/ subdir)
    _dash_path = Path(__file__).resolve().parent.parent.parent / "docs" / "data" / "sally.json"
    try:
        _dash_path.parent.mkdir(parents=True, exist_ok=True)
        _dash_path.write_text(
            json.dumps(
                {
                    "last_run": now_local.date().isoformat(),
                    "portfolio_size": len(portfolio),
                    "flagged_count": flag_count,
                    "flagged": [
                        {
                            "ticker": r["ticker"],
                            "company_name": r.get("company_name", ""),
                            "current_price": r.get("current_price", 0),
                            "high_52w": r.get("high_52w", 0),
                            "distance_to_high_pct": r.get("distance_to_high_pct", 0),
                            "trailing_pe": r.get("trailing_pe"),
                            "forward_pe": r.get("forward_pe"),
                            "dividend_yield": r.get("dividend_yield"),
                            "valuation_percentile": r.get("valuation_percentile"),
                            "alert_tier": r.get("alert_tier", ""),
                            "sally_verdict": r.get("sally_verdict", ""),
                            "harry_flag": bool(r.get("harry_flag")),
                            "wedge_zone": r.get("wedge_zone"),
                            "wedge_position": r.get("wedge_position"),
                            "wedge_buy_value": r.get("wedge_buy_value"),
                            "wedge_sell_value": r.get("wedge_sell_value"),
                            "wedge_actual_pe": r.get("wedge_actual_pe"),
                            "ranges_52w": r.get("ranges_52w"),
                        }
                        for r in flagged_rows
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[sally] Dashboard data written → {_dash_path}")
    except Exception as _e:
        print(f"[sally] Dashboard write failed: {_e}")

    print(json.dumps(run_log, indent=2))


if __name__ == "__main__":
    main()
