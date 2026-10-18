#!/usr/bin/env python3
"""
scripts/eodhd_check.py

Show, for each ticker, the exact numbers the agents will use, straight from
EODHD, so they can be checked against the company's own report or a broker
screen. Nothing here is estimated: a figure EODHD does not have prints as
"n/a" with the reason.

  python scripts/eodhd_check.py                 # the portfolio (tickers.yaml)
  python scripts/eodhd_check.py PWH BHP RR.L    # just these
  python scripts/eodhd_check.py --watchlists    # portfolio + every Wally watchlist
  python scripts/eodhd_check.py PWH --detail    # plus the EPS working, year by year

Writes outputs/eodhd_check.md (and appends it to the GitHub job summary when
run in Actions). Exit code 1 if EODHD is not configured or every ticker
failed, so a broken token cannot pass silently.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

from shared import eodhd  # noqa: E402
from shared.securities import ASX, LSE, US  # noqa: E402


def _fmt(v, kind: str = "num") -> str:
    if v is None:
        return "n/a"
    if kind == "pct":
        return f"{v * 100:.2f}%"
    if kind == "big":
        return f"{v / 1e6:,.0f}m"
    if kind == "x":
        return f"{v:.1f}x"
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"


def portfolio_tickers() -> list[tuple[str, str]]:
    data = yaml.safe_load((REPO / "tickers.yaml").read_text(encoding="utf-8")) or {}
    out = [(str(t), ASX) for t in (data.get("asx") or {})]
    out += [(str(t), LSE) for t in (data.get("lse") or {})]
    out += [(str(t), US) for t in (data.get("us") or {})]
    out += [(f"{t}.SI", ASX) for t in (data.get("sgx") or {})]  # listed so the gap is visible
    return out


def watchlist_tickers() -> list[tuple[str, str]]:
    from wally.watchlist_loader import load_watchlist

    out = []
    for path in sorted((REPO / "watchlists").glob("*.yaml")):
        try:
            out += [(t, US) for t in load_watchlist(path).tickers]  # Wally: .AX = ASX, bare = US
        except Exception as e:
            print(f"[eodhd_check] could not read {path.name}: {e}")
    return out


def check(raw: str, default_exchange: str, detail: bool) -> tuple[list[str], list[str]]:
    """One table row, plus optional detail lines."""
    try:
        sym = eodhd.symbol(raw, default_exchange)
    except eodhd.EODHDError as e:
        return [raw, "-", "NOT COVERED", str(e), "", "", "", "", "", "", ""], []
    try:
        p = eodhd.price_summary(sym)
    except eodhd.EODHDError as e:
        return [raw, sym, "NO PRICE", str(e), "", "", "", "", "", "", ""], []

    snap, eps_rows, all_rows, note = None, [], [], ""
    try:
        fund = eodhd.fundamentals(sym)
        snap = eodhd.snapshot(sym, fund)
        all_rows = eodhd.annual_eps(sym, fund, include_rejected=True)
        eps_rows = [r for r in all_rows if not r.get("rejected")]
    except eodhd.EODHDError as e:
        note = f"fundamentals: {e}"

    last_eps = eps_rows[-1] if eps_rows else None
    eps_txt = (f"{last_eps['eps'] * 100:.2f}c FY{last_eps['fiscal_end'][:4]}" if last_eps else "n/a")
    row = [
        raw, sym, "OK" if snap else "PRICE ONLY",
        f"{p.last:,.3f} {p.currency or ''} ({p.last_date})",
        f"{p.low_52w:,.3f} - {p.high_52w:,.3f}",
        _fmt(snap and snap.trailing_pe, "x"), _fmt(snap and snap.forward_pe, "x"),
        _fmt(snap and snap.market_cap, "big"), _fmt(snap and snap.dividend_yield, "pct"),
        eps_txt, note or (f"{len(eps_rows)} EPS years"
                          + (f", {len(all_rows) - len(eps_rows)} rejected" if len(all_rows) > len(eps_rows) else "")),
    ]
    lines = []
    if detail:
        lines.append(f"\n### {raw} ({sym}) EPS working: net income / shares on issue at balance date\n")
        lines.append("| Fiscal year end | Released | Net income | Shares | EPS (cents) |")
        lines.append("|---|---|---|---|---|")
        for r in all_rows:
            eps_cell = (f"NOT USED: {r['rejected']}" if r.get("rejected") else f"{r['eps'] * 100:.2f}")
            lines.append(f"| {r['fiscal_end']} | {r['release_date'] or 'n/a (2-month deadline used)'} | "
                         f"{r['net_income'] / 1e6:,.2f}m {r['currency'] or ''} | {r['shares'] / 1e6:,.2f}m | "
                         f"{eps_cell} |")
        divs = eodhd.dividends_by_year(sym)
        if divs:
            lines.append("\nDividends per share by calendar year (EODHD /div, unadjusted): "
                         + ", ".join(f"{y}: {v * 100:.2f}c" for y, v in sorted(divs.items())[-6:]))
        if snap and snap.notes:
            lines.append("\n" + "; ".join(snap.notes))
    return row, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="*", help="tickers to check (default: tickers.yaml portfolio)")
    ap.add_argument("--watchlists", action="store_true", help="also check every Wally watchlist")
    ap.add_argument("--detail", action="store_true", help="show the EPS working per year")
    ap.add_argument("--out", default=str(REPO / "outputs" / "eodhd_check.md"))
    args = ap.parse_args(argv)

    if not eodhd.is_configured():
        print("EODHD_API_TOKEN is not set: no market data can be fetched.")
        return 1

    targets = [(t, ASX) for t in args.tickers] if args.tickers else portfolio_tickers()
    if args.watchlists:
        targets += watchlist_tickers()
    seen, unique = set(), []
    for t, ex in targets:
        try:
            key = eodhd.symbol(t, ex)
        except eodhd.EODHDError:
            key = t
        if key not in seen:
            seen.add(key)
            unique.append((t, ex))

    header = ["Ticker", "EODHD symbol", "Status", "Last close", "52w range", "PE (TTM)",
              "Fwd PE", "Mkt cap", "Div yield", "Latest annual EPS", "Notes"]
    out = ["# EODHD data check", "",
           "Every figure below is exactly what Bob, Wally, Sally, Harry and Esther now use. "
           "Spot-check a few against the annual report or your broker.", "",
           "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    details, ok = [], 0
    for raw, ex in unique:
        row, lines = check(raw, ex, args.detail)
        ok += row[2] in ("OK", "PRICE ONLY")
        out.append("| " + " | ".join(str(c).replace("|", "/") for c in row) + " |")
        details += lines
    out += details
    out += ["", f"{ok}/{len(unique)} tickers priced. EODHD requests this run: {eodhd.stats['requests']}."]
    text = "\n".join(out) + "\n"

    print(text)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
