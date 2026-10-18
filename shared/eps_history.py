"""Reported annual EPS history from EODHD, in the row shape valuations/*.yaml use.

One place for both readers of those files: Sally's value wedge and Wally's
value-chart workbook. A valuation YAML with ``earnings_source: eodhd`` (or no
YAML at all, for Sally) gets its ``earnings:`` rows from here at run time
instead of from hand-typed numbers. No estimates: every figure is EODHD's
statutory net income divided by the checked share count (``eodhd.annual_eps``),
usable from its release date.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


def eodhd_earnings_rows(ticker: str, *, fund: Optional[dict] = None, divs: Optional[dict] = None,
                        years: int = 12, today: Optional[dt.date] = None) -> tuple[list[dict], str]:
    """([{date, period, period_end, ttm_eps, ttm_div, source, notes}], statement currency).

    ``ttm_eps`` is cents (or pence) per share in the statement currency.
    ``ttm_div`` is the cash dividends with ex-dates in the calendar year the
    financial year ends (interim + final for a June year end), in the trading
    currency; None when EODHD has no dividend record. Only Wally's old
    workbook reads dividends."""
    from shared import eodhd
    today = today or dt.date.today()
    sym = eodhd.symbol(ticker)
    fund = fund if fund is not None else eodhd.fundamentals(sym)
    rows = [r for r in eodhd.annual_eps(sym, fund) if r.get("eps") is not None]
    cutoff = today - dt.timedelta(days=round(365.25 * years))
    rows = [r for r in rows if dt.date.fromisoformat(r["fiscal_end"][:10]) >= cutoff]
    if divs is None:
        try:
            divs = eodhd.dividends_by_year(sym, cutoff)
        except eodhd.EODHDError:
            divs = {}
    out = []
    for r in rows:
        end = r["fiscal_end"][:10]
        div = divs.get(end[:4])
        out.append({
            "date": eodhd.known_from(r),
            "period": f"FY{end[:4]}",
            "period_end": end,
            "ttm_eps": round(r["eps"] * 100, 3),
            "ttm_div": round(div * 100, 2) if div is not None else None,
            "source": "EODHD income statement",
            "notes": (f"Statutory NPAT {r['net_income'] / 1e6:,.1f}m / {r['shares'] / 1e6:,.1f}m shares; "
                      + ("EODHD report date" if r.get("release_date") else "release = two months after year end")),
        })
    ccy = str((rows[-1].get("currency") if rows else "") or "").upper()
    return out, ccy
