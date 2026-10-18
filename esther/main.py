"""Esther the Wrestler: run one or more companies and email JM the result.

    python -m esther run --tickers CPU,BXB,BHP,NHC                 # full narratives
    python -m esther run --tickers NHC --mode challenge            # CHALLENGE MY THESIS
    python -m esther run --tickers CPU --mode thesis               # THESIS CHECK
    python -m esther run --tickers BHP --mode valuation --price BHP=59.80
    python -m esther run --tickers NHC --source NHC=https://www.asx.com.au/...pdf --notes "focus on New Acland"
    python -m esther run --tickers CPU --analysis-dir some/dir     # render a saved analysis, no model call

Modes map onto the spec's buttons: full (FULL NARRATIVE), quick (QUICK UPDATE),
valuation (VALUATION ONLY / CHANGE VALUATION), thesis (THESIS CHECK),
challenge (CHALLENGE MY THESIS). Re-running is REGENERATE.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from esther import analyst, context, market, quality, render, store
from esther.valuation import BaseFigures, Scenario, ValuationInputError, run_valuation

REPO_ROOT = context.REPO_ROOT
OUT_ROOT = REPO_ROOT / "outputs" / "esther"
DEFAULT_DISCOUNT = 0.075

Log = Callable[[str], None]


def _print(msg: str) -> None:
    print(msg, flush=True)


def _kv_list(items: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw in items or []:
        for part in [p for p in raw.replace("\n", ",").split(",") if p.strip()]:
            if "=" not in part:
                raise SystemExit(f"expected TICKER=value, got {part!r}")
            k, v = part.split("=", 1)
            out.setdefault(context.norm(k), []).extend(x.strip() for x in v.split("|") if x.strip())
    return out


def _case(raw: dict, name: str) -> Scenario:
    try:
        why = raw.get("rationale", "")
        if isinstance(why, dict):
            why = " ".join(f"{k.replace('_', ' ').capitalize()}: {v}" for k, v in why.items() if v)
        s = Scenario(name=name, revenue_growth=float(raw["revenue_growth"]), net_margin=float(raw["net_margin"]),
                     future_pe=float(raw["future_pe"]), rationale=str(why))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValuationInputError(f"{name} is missing revenue_growth, net_margin or future_pe")
    s.validate()
    return s


def cases_from(analysis: dict) -> tuple[Scenario, Optional[Scenario]]:
    """The published Narrative case (required) and JM's private stress case (optional)."""
    narrative = _case(analysis.get("narrative_case") or {}, "narrative case")
    stress = None
    if analysis.get("stress_case"):
        try:
            stress = _case(analysis["stress_case"], "stress case")
        except ValuationInputError:
            stress = None  # a malformed private check never blocks the published case
    return narrative, stress


def _qc_errors(analysis: dict) -> list[str]:
    errs = list(quality.check(analysis).hard_errors)
    try:
        cases_from(analysis)
    except ValuationInputError as exc:
        errs.append(f"narrative_case: {exc}")
    return errs


def build_base(analysis: dict, ticker: str, price_override: Optional[float], use_market: bool,
               log: Log) -> tuple[BaseFigures, Optional[float], list[str]]:
    """Base figures from the model's sourced numbers, with live price/shares/FX where available."""
    bf = analysis.get("base_figures") or {}
    sources = [f"Revenue: {bf.get('revenue_period', 'period n/a')}, {bf.get('source', 'source not given')}"]
    report_ccy = (bf.get("report_currency") or "AUD").upper()
    price_ccy = (bf.get("price_currency") or "AUD").upper()
    shares = bf.get("shares_m")
    price = bf.get("price")
    price_note = (f"Price {bf.get('price')} ({bf.get('price_date', 'date n/a')}) as sourced by Esther's research: "
                  "NOT verified, EODHD had no quote")

    quote = market.fetch_quote(ticker, log=log) if use_market else market.Quote(source="disabled")
    if quote.price:
        price, price_ccy = quote.price, (quote.currency or price_ccy).upper()
        price_note = f"Price {quote.price:.2f} {price_ccy} close {quote.as_of} (EODHD)"
    if quote.shares_m:
        sources.append(f"Shares {quote.shares_m:,.1f}m (EODHD); Esther's research said {shares}m")
        shares = quote.shares_m
    else:
        sources.append(f"Shares {shares}m as sourced by Esther's research: NOT verified, EODHD had no share count")
    if price_override:
        price = price_override
        price_note = f"Price {price_override} set by JM for this run"
    sources.append(price_note)

    fx = 1.0
    if report_ccy != price_ccy:
        live = market.fx_rate(report_ccy, price_ccy, log=log) if use_market else None
        given = bf.get("fx_report_to_price")
        fx = live or (float(given) if given else None)
        if not fx:
            raise ValuationInputError(f"no {report_ccy}->{price_ccy} FX rate available")
        sources.append(f"FX {report_ccy}/{price_ccy} {fx:.4f} ({'EODHD' if live else 'as sourced by Esther: NOT verified, EODHD had no rate'})")

    base = BaseFigures(
        revenue_m=float(bf.get("revenue_m") or 0),
        shares_m=float(shares or 0),
        report_currency=report_ccy,
        price_currency=price_ccy,
        fx_report_to_price=fx,
        years=5,
        discount_rate=float(bf.get("discount_rate") or DEFAULT_DISCOUNT),
        share_change_pa=float(bf.get("share_change_pa") or 0.0),
        dps=float(bf.get("dps") or 0.0),
    )
    return base, (float(price) if price else None), sources


def _source_blocks(urls: list[str], files: list[str], log: Log) -> tuple[list, dict[str, str]]:
    """PDFs become native document blocks; text files and failed downloads become context sections."""
    from shared.pdf_llm import PdfAttachment, build_pdf_attachments

    atts, sections = [], {}
    for url in urls:
        try:
            from shared.asx import browser_session

            sess = browser_session(accept="application/pdf,*/*")
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            if r.content[:4] == b"%PDF":
                atts.append(PdfAttachment(name=url, pdf_bytes=r.content))
            else:
                sections[f"Source {url}"] = r.text[:60000]
        except Exception as exc:
            sections[f"Source {url} (could not download)"] = f"{type(exc).__name__}: {exc}"
    for f in files:
        p = Path(f)
        try:
            if p.suffix.lower() == ".pdf":
                atts.append(PdfAttachment(name=p.name, pdf_bytes=p.read_bytes()))
            else:
                sections[f"Source file {p.name}"] = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            sections[f"Source file {p.name} (unreadable)"] = str(exc)
    blocks: list = []
    if atts:
        batch = build_pdf_attachments(atts, log=log)
        blocks = batch.document_blocks
        for i, s in enumerate(batch.fallback_sections):
            sections[f"Extracted source text {i + 1}"] = s
    return blocks, sections


def run_one(ticker: str, *, mode: str, notes: str, price: Optional[float], urls: list[str], files: list[str],
            analysis_dir: Optional[Path], use_market: bool, web_search: bool, run_date: str,
            log: Log = _print) -> render.Report:
    prev = store.load_previous(ticker)
    blocks, extra = _source_blocks(urls, files, log)
    ctx = context.gather(ticker, previous=prev, extra_sections=extra)
    rep = render.Report(ticker=ctx.ticker, company=ctx.company, status=analyst.FAILED_API, portfolio=ctx.portfolio)

    if analysis_dir:
        path = analysis_dir / f"{ctx.ticker}.json"
        try:
            a = analyst.clean(json.loads(path.read_text(encoding="utf-8")))
            errs = _qc_errors(a)
            res = analyst.AnalystResult(status=analyst.OK if not errs else analyst.FAILED_INVALID, analysis=a,
                                        error="; ".join(errs))
        except Exception as exc:
            res = analyst.AnalystResult(status=analyst.FAILED_INVALID, error=f"{path}: {exc}")
    else:
        from esther.prompts import build_user_prompt

        res = analyst.analyse(build_user_prompt(ctx.as_prompt(), mode, notes), content_blocks=blocks,
                              qc_errors_for=_qc_errors, web_search=web_search, log=log)
    rep.status, rep.analysis, rep.error = res.status, res.analysis, res.error
    rep._usage = (res.calls, res.input_tokens, res.output_tokens)  # type: ignore[attr-defined]
    if ctx.company == ctx.ticker and rep.analysis.get("company"):
        rep.company = rep.analysis["company"]

    if rep.analysis:
        try:
            base, px, rep.figure_sources = build_base(rep.analysis, ctx.ticker, price, use_market, log)
            narrative, stress = cases_from(rep.analysis)
            rep.valuation = run_valuation(narrative, base, px, stress=stress)
        except ValuationInputError as exc:
            rep.valuation_error = str(exc)
        rep.qc = quality.check(rep.analysis, rep.valuation.warnings if rep.valuation else [rep.valuation_error])

    if rep.status == analyst.OK:
        store.save(ctx.ticker, {"date": run_date, "mode": mode, "analysis": rep.analysis,
                                "valuation": rep.valuation.to_dict() if rep.valuation else None})
    return rep


def run(tickers: list[str], mode: str = "full", notes: str = "", prices: Optional[dict] = None,
        sources: Optional[dict] = None, files: Optional[dict] = None, analysis_dir: Optional[Path] = None,
        send_email: bool = True, use_market: bool = True, web_search: bool = True, log: Log = _print) -> list[render.Report]:
    if mode not in render.MODES:
        raise SystemExit(f"mode must be one of {', '.join(render.MODES)}")
    cap = int(os.environ.get("ESTHER_MAX_TICKERS") or 8)
    run_date = dt.date.today().isoformat()
    out_dir = OUT_ROOT / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    for i, t in enumerate(tickers):
        t = context.norm(t)
        if i >= cap:
            ctx = context.gather(t)
            reports.append(render.Report(ticker=t, company=ctx.company, status=analyst.SKIPPED_CAP,
                                         portfolio=ctx.portfolio, error=f"ESTHER_MAX_TICKERS={cap} reached"))
            continue
        log(f"[esther] {t}: {mode}")
        px = (prices or {}).get(t)
        rep = run_one(t, mode=mode, notes=notes, price=float(px[0]) if px else None,
                      urls=(sources or {}).get(t, []), files=(files or {}).get(t, []),
                      analysis_dir=analysis_dir, use_market=use_market, web_search=web_search,
                      run_date=run_date, log=log)
        log(f"[esther] {t}: {rep.status}" + (f" ({rep.error})" if rep.error else ""))
        reports.append(rep)

    md_paths = []
    for r in reports:
        p = out_dir / f"{r.ticker}.md"
        p.write_text(render.to_markdown(r, mode), encoding="utf-8")
        md_paths.append(p)

    calls = sum(getattr(r, "_usage", (0, 0, 0))[0] for r in reports)
    tin = sum(getattr(r, "_usage", (0, 0, 0))[1] for r in reports)
    tout = sum(getattr(r, "_usage", (0, 0, 0))[2] for r in reports)
    stats = f"{len(reports)} compan{'y' if len(reports) == 1 else 'ies'}, {calls} model call(s), {tin:,} in / {tout:,} out tokens"
    html_body = render.email_html(reports, mode, run_date, stats)
    text_body = render.email_text(reports, mode, run_date, stats)
    (out_dir / "email.html").write_text(html_body, encoding="utf-8")

    worst = next((r.status for r in reports if r.status != analyst.OK), "OK")
    subject = (f"Esther the Wrestler | {run_date} | {mode.upper()} | {', '.join(r.ticker for r in reports)}"
               + ("" if worst == "OK" else f" | {worst}"))
    if send_email:
        from shared.email_service import send_email as _send

        _send(subject, text_body, html_body, attachments=md_paths, raise_on_error=False, log=log,
              log_prefix="[esther]")
    log(f"[esther] wrote {out_dir}")
    return reports


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m esther", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tickers", required=True, help="comma separated, e.g. CPU,BXB,BHP,NHC")
    r.add_argument("--mode", default="full", choices=render.MODES)
    r.add_argument("--notes", default="", help="JM's steer for this run")
    r.add_argument("--price", action="append", default=[], help="TICKER=price override, e.g. BHP=59.80")
    r.add_argument("--source", action="append", default=[], help="TICKER=url[|url], ASX PDF or web page")
    r.add_argument("--source-file", action="append", default=[], help="TICKER=path[|path], PDF or text")
    r.add_argument("--analysis-dir", type=Path, help="render saved TICKER.json analyses instead of calling the model")
    r.add_argument("--no-email", action="store_true")
    r.add_argument("--no-market", action="store_true", help="skip EODHD price/shares/FX lookups")
    r.add_argument("--no-web-search", action="store_true")
    args = p.parse_args(argv)

    reports = run([t for t in args.tickers.replace(" ", "").split(",") if t], mode=args.mode, notes=args.notes,
                  prices=_kv_list(args.price), sources=_kv_list(args.source), files=_kv_list(args.source_file),
                  analysis_dir=args.analysis_dir, send_email=not args.no_email, use_market=not args.no_market,
                  web_search=not args.no_web_search)
    return 0 if all(r.status == analyst.OK for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
