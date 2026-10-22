# mike/main.py
#
# Mike: Mikebrisy's Stock Quality Assessment Framework v3.1, on email rails.
#
#   python -m mike --list mikebrisy_sample --email
#   python -m mike --list portfolio --email            # open holdings, ETFs excluded
#   python -m mike --tickers PME,TNE --no-evidence     # quantitative only (DRAFT)
#   python -m mike --tickers PME --cache-dir qcache    # reuse saved /fundamentals JSON
#
# Fundamentals: shared/eodhd.py, one /fundamentals call per company.
# Evidence review: one Claude call per company (web search), in parallel.
# Output: outputs/mike/<run>/mike_report.pdf, mike.json, email.html.

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import yaml

from mike import report
from mike.assess import Assessment, assess, load_archetypes, load_config

ROOT = Path(__file__).resolve().parent.parent
ETFS = {"VAS", "VEU", "VHY", "VGS", "IVV", "NDQ", "A200", "STW", "IOZ", "VTS"}
TITLES = {"mikebrisy_sample": "Mikebrisy's sample (Strawman, Oct 2026)", "portfolio": "JM portfolio, ETFs excluded"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def portfolio_tickers() -> list[str]:
    """Open decisions in the ledger, ETFs out. LSE names keep their repo spelling (RR.)."""
    data = json.loads((ROOT / "data" / "decisions.json").read_text(encoding="utf-8"))
    lse = set((yaml.safe_load((ROOT / "tickers.yaml").read_text(encoding="utf-8")) or {}).get("lse") or {})
    out = []
    for d in data.get("decisions") or []:
        t = str(d.get("ticker") or "").upper()
        if d.get("status") != "OPEN" or not t or t in ETFS:
            continue
        t = f"{t}." if f"{t}." in lse else t
        if t not in out:
            out.append(t)
    return sorted(out)


def resolve_list(name: str, config: dict) -> list[str]:
    if name == "portfolio":
        return portfolio_tickers()
    lst = (config.get("lists") or {}).get(name)
    if not lst:
        raise SystemExit(f"[mike] unknown list '{name}' (config/mike.yaml lists, or 'portfolio')")
    return [str(t).upper() for t in lst]


def load_fundamentals(code: str, cache_dir: Optional[Path]) -> dict:
    from shared import eodhd
    sym = eodhd.symbol(code)
    if cache_dir:
        p = cache_dir / f"{sym}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    fund = eodhd.fundamentals(sym)
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{sym}.json").write_text(json.dumps(fund), encoding="utf-8")
    return fund


def run(tickers: list[str], title: str, *, out_dir: Path, cache_dir: Optional[Path] = None,
        use_evidence: bool = True, gather: Optional[Callable] = None, workers: int = 4,
        when: Optional[dt.datetime] = None, log: Callable[[str], None] = print) -> dict:
    when = when or dt.datetime.now()
    config, archetypes = load_config(), load_archetypes()
    max_calls = int(os.environ.get("MIKE_MAX_LLM_CALLS") or 40)

    funds: dict[str, Optional[dict]] = {}
    errors: dict[str, str] = {}
    for t in tickers:
        try:
            funds[t] = load_fundamentals(t, cache_dir)
        except Exception as exc:  # noqa: BLE001  EODHD error / not covered / no token
            funds[t] = None
            errors[t] = f"no EODHD fundamentals ({exc.__class__.__name__}: {exc})"
            log(f"[mike] {t}: {errors[t]}")

    def one(i_t):
        i, t = i_t
        if funds.get(t) is None:
            a = Assessment(ticker=t.rstrip("."), name=t, error=errors.get(t, "no data"))
            return a
        ev_on = use_evidence and i < max_calls
        a = assess(t, funds[t], config=config, archetypes=archetypes, gather=gather, use_evidence=ev_on, log=log)
        if use_evidence and not ev_on:
            a.evidence_status = f"SKIPPED: run cap MIKE_MAX_LLM_CALLS={max_calls} reached"
        log(f"[mike] {a.ticker}: overall {a.overall} {a.classification} | evidence {a.evidence_status or 'n/a'}")
        return a

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        assessments = list(pool.map(one, enumerate(tickers)))

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / "mike_report.pdf"
    pdf_ok = False
    try:
        # Render, inspect, certify, then render the final version and inspect it again (8.7).
        report.render_pdf(report.build_pdf_html(assessments, title, when), pdf_path)
        checks = report.inspect_pdf(pdf_path, assessments)
        for a in assessments:
            a.render_ok, a.render_note = checks.get(a.ticker, (False, "not found"))
            a.finalise()
        report.render_pdf(report.build_pdf_html(assessments, title, when), pdf_path)
        final = report.inspect_pdf(pdf_path, assessments)
        bad = [t for t, (ok, _) in final.items() if not ok]
        for a in assessments:
            if a.ticker in bad and a.status == "PASS":
                a.render_ok, a.render_note = False, final[a.ticker][1]
                a.finalise()
        pdf_ok = pdf_path.exists() and not bad
    except Exception as exc:  # noqa: BLE001
        log(f"[mike] PDF render failed: {exc.__class__.__name__}: {exc}")
        for a in assessments:
            a.render_ok, a.render_note = False, f"PDF render failed ({exc.__class__.__name__})"
            a.finalise()

    html = report.email_html(assessments, title, when, pdf_ok)
    (out_dir / "email.html").write_text(html, encoding="utf-8")
    (out_dir / "mike.json").write_text(json.dumps({"title": title, "generated": when.isoformat(timespec="seconds"),
                                                   "assessments": [a.as_dict() for a in assessments]},
                                                  indent=1, default=str), encoding="utf-8")
    n_pass = sum(a.status == "PASS" for a in assessments)
    log(f"[mike] {len(assessments)} assessed, {n_pass} PASS; outputs in {out_dir}")
    return {"assessments": assessments, "html": html, "text": report.email_text(assessments, title),
            "pdf": pdf_path if pdf_path.exists() else None, "pdf_ok": pdf_ok, "title": title, "n_pass": n_pass}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mike", description="Mikebrisy's Stock Quality Assessment Framework v3.1")
    ap.add_argument("--list", default="", help="mikebrisy_sample | portfolio | any list in config/mike.yaml")
    ap.add_argument("--tickers", default="", help="comma or space separated; overrides --list")
    ap.add_argument("--title", default="")
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--no-evidence", action="store_true", help="skip the Market Position evidence review (all DRAFT)")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("MIKE_WORKERS") or 4))
    a = ap.parse_args(argv)

    config = load_config()
    if a.tickers.strip():
        tickers = [t.strip().upper() for t in re.split(r"[,\s]+", a.tickers) if t.strip()]
        name = "custom"
    else:
        name = a.list or "portfolio"
        tickers = resolve_list(name, config)
    title = a.title or TITLES.get(name, "Custom list")
    out = a.out or ROOT / "outputs" / "mike" / name
    res = run(tickers, title, out_dir=out, cache_dir=a.cache_dir, use_evidence=not a.no_evidence, workers=a.workers)

    if a.email:
        from shared.email_service import send_email
        subject = f"Mike [Quality] {title}: {len(res['assessments'])} companies, {res['n_pass']} PASS"
        sent = send_email(subject, res["text"], res["html"],
                          attachments=[res["pdf"]] if res["pdf"] else None,
                          raise_on_error=False, log_prefix="[mike]")
        print(f"[mike] email {'sent' if sent else 'NOT sent'}")
        if not sent:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
