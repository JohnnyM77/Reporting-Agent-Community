"""52-week ranges from EODHD: price, P/E and P/FCF.

Three jobs:
  * pull EOD prices and fundamentals through shared/eodhd.py (the one
    market-data source; no second client here)
  * work out the 52-week low / high / current, and the daily series, for
    price, P/E (TTM) and P/FCF (TTM)
  * render a tight, email-safe HTML range bar (tables + inline styles only)
    and, via shared/range_chart.py, a small inline PNG of the P/E and P/FCF
    lines

How the multiples are built (arithmetic on EODHD numbers, never estimates):
  * TTM net income and TTM free cash flow are summed from EODHD's period
    statements (half-years for most ASX names, quarters for US), cadence
    detected from the gaps. PWH: 1H25 4.08m + 2H25 5.68m = FY25 9.77m.
  * Each TTM figure is divided by shares on issue at that period end
    (eodhd's checked share count: a period whose count fails the check is a
    gap, not a guess) and applies from its release date: EODHD's reportDate
    when it is after the period end, else period end + 61 days. No look-ahead.
  * A foreign-currency reporter is converted once, at the FX rate on the
    release date (same rule as Sally's wedge); LSE pence handled.
  * Loss or negative FCF -> no multiple for those days (a gap), never a
    made-up number. EODHD's rounded Earnings.History epsActual is NOT used:
    it put PWH's TTM EPS at 12c (82x) when the statements say 17.8c (55x).

Never raises: anything that goes wrong returns None for that metric and the
cell shows "n/a".
"""
from __future__ import annotations

import datetime as dt
import statistics
from typing import Callable, Optional

from shared import eodhd
from shared.securities import US

_CACHE: dict[str, dict | None] = {}

LABELS = {"price": "52W Price", "pe": "52W P/E", "pfcf": "52W P/FCF"}
BASIS = "Statutory, trailing 12 months, from EODHD statements; each result counts from its release date."

FxLookup = Callable[[str, str, dt.date], Optional[float]]


# ── TTM maths ────────────────────────────────────────────────────────────────

def _d(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def _num(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _ttm_series(points: list[tuple[dt.date, dt.date, float]]) -> list[tuple[dt.date, dt.date, float]]:
    """points = (period_end, known_from, value). Returns [(period_end, known_from, ttm)].

    Cadence is detected from the gaps between period ends: quarterly sums 4,
    half-yearly (most ASX reporters) sums 2, annual takes 1. A window with a
    missing period is skipped rather than understated.
    """
    pts = sorted(p for p in points if p[2] is not None)
    if not pts:
        return []
    gaps = [(b[0] - a[0]).days for a, b in zip(pts, pts[1:]) if (b[0] - a[0]).days > 0]
    gap = statistics.median(gaps) if gaps else 365
    n = 1 if gap > 300 else 2 if gap > 120 else 4
    out = []
    for i in range(n - 1, len(pts)):
        window = pts[i - n + 1 : i + 1]
        if (window[-1][0] - window[0][0]).days > gap * (n - 1) * 1.5 + 10:
            continue
        out.append((window[-1][0], window[-1][1], sum(p[2] for p in window)))
    return out


def _value_at(series: list[tuple[dt.date, Optional[float]]], day: dt.date) -> float | None:
    val = None
    for known, v in series:
        if known <= day:
            val = v
        else:
            break
    return val


def _known_from(f: dict, end: dt.date) -> dt.date:
    rel = _d(((f.get("Earnings") or {}).get("History") or {}).get(end.isoformat(), {}).get("reportDate"))
    return rel if rel and rel > end else end + dt.timedelta(days=61)


def _statement_points(f: dict, stmt: str, field: str) -> list[tuple[dt.date, dt.date, float]]:
    """Period values from the quarterly (incl. half-year) statements, else yearly."""
    fin = (f.get("Financials") or {}).get(stmt) or {}
    for block in ("quarterly", "yearly"):
        pts = []
        for row in (fin.get(block) or {}).values():
            end = _d(row.get("date"))
            val = _num(row.get(field))
            if val is None and field == "netIncome":
                val = _num(row.get("netIncomeApplicableToCommonShares"))
            if val is None and field == "freeCashFlow":
                ocf, capex = _num(row.get("totalCashFromOperatingActivities")), _num(row.get("capitalExpenditures"))
                if ocf is not None and capex is not None:
                    val = ocf - abs(capex)
            if end is not None and val is not None:
                pts.append((end, _known_from(f, end), val))
        if len(pts) >= 2:
            return pts
    return []


def _statement_ccy(f: dict) -> str | None:
    fin = f.get("Financials") or {}
    for stmt in ("Income_Statement", "Cash_Flow", "Balance_Sheet"):
        if (fin.get(stmt) or {}).get("currency_symbol"):
            return fin[stmt]["currency_symbol"]
        for block in ("quarterly", "yearly"):
            for row in ((fin.get(stmt) or {}).get(block) or {}).values():
                if row.get("currency_symbol"):
                    return row["currency_symbol"]
    return None


def _per_share(f: dict, ttm: list[tuple[dt.date, dt.date, float]], conv: Callable[[dt.date], Optional[float]],
               notes: list[str], what: str, since: Optional[dt.date] = None) -> list[tuple[dt.date, Optional[float]]]:
    """[(known_from, per-share value in the price's currency)], None = gap.

    Periods released before ``since`` are skipped entirely: only the figure in
    force at the start of the window and later ones can reach the chart, and a
    note about a 1990s period nobody sees is noise (CPU's email once carried
    ~120 "no FX rate" notes back to 1994)."""
    out = []
    if since is not None:
        in_force = max((k for _, k, _ in ttm if k <= since), default=None)
        ttm = [t for t in ttm if in_force is None or t[1] >= in_force]
    for end, known, total in ttm:
        shares, problem = eodhd._shares_at(f, end.isoformat())
        rate = conv(known)
        if not shares or problem or rate is None:
            if problem:
                notes.append(f"{what} gap after {end:%b %Y}: {problem}")
            elif rate is None:
                notes.append(f"{what} gap after {end:%b %Y}: no FX rate")
            out.append((known, None))
            continue
        out.append((known, total / shares * rate))
    return sorted(out, key=lambda p: p[0])


def _range(values: list[Optional[float]], current: float | None) -> dict | None:
    vals = [v for v in values if v is not None]
    if not vals or current is None:
        return None
    lo, hi = min(vals), max(vals)
    pos = 0.5 if hi == lo else (current - lo) / (hi - lo)
    return {"low": round(lo, 4), "high": round(hi, 4), "current": round(current, 4),
            "position": round(max(0.0, min(1.0, pos)), 4)}


def compute_ranges(prices: list[dict], fundamentals: dict | None, price_ccy: str | None = None,
                   fx: FxLookup | None = None) -> dict:
    """Pure function (testable offline).

    prices = EODHD eod rows, oldest first. ``price_ccy`` is the quote unit
    (AUD / USD / GBX). ``fx(from, to, day)`` returns *to* per one *from* on
    *day*; only needed when the statements are in another currency.
    """
    out: dict = {"price": None, "pe": None, "pfcf": None, "notes": [], "basis": BASIS,
                 "series": {"dates": [], "pe": [], "pfcf": [], "results": [], "pe_gap": [], "pfcf_gap": []}}
    rows = [r for r in prices if _d(r.get("date")) and _num(r.get("close"))]
    if not rows:
        return out
    last = _d(rows[-1]["date"])
    rows = [r for r in rows if _d(r["date"]) > last - dt.timedelta(days=365)]
    closes = [(_d(r["date"]), float(r["close"])) for r in rows]
    highs = [_num(r.get("high")) or float(r["close"]) for r in rows]
    lows = [_num(r.get("low")) or float(r["close"]) for r in rows]
    out["price"] = _range(lows + highs, closes[-1][1])
    out["series"]["dates"] = [d.isoformat() for d, _ in closes]

    f = fundamentals or {}
    if not f:
        return out
    price_ccy = (price_ccy or (f.get("General") or {}).get("CurrencyCode") or "").upper()
    stmt_ccy = (_statement_ccy(f) or price_ccy).upper()

    def conv(day: dt.date) -> Optional[float]:
        base, scale = price_ccy, 1.0
        if base == "GBX":                      # LSE quotes in pence
            base, scale = "GBP", 100.0
        if stmt_ccy == base:
            return scale
        rate = fx(stmt_ccy, base, day) if fx else None
        return rate * scale if rate else None

    if stmt_ccy and price_ccy and stmt_ccy != price_ccy and not (price_ccy == "GBX" and stmt_ccy == "GBP"):
        out["notes"].append(f"{stmt_ccy} reporter, converted at the FX rate on each release date")

    for key, field, what in (("pe", "netIncome", "P/E"), ("pfcf", "freeCashFlow", "P/FCF")):
        stmt = "Income_Statement" if key == "pe" else "Cash_Flow"
        per_share = _per_share(f, _ttm_series(_statement_points(f, stmt, field)), conv, out["notes"], what,
                               since=closes[0][0])
        if not per_share:
            out["notes"].append(f"{what} n/a: no {stmt.replace('_', ' ').lower()} history in EODHD")
            out["series"][key] = [None] * len(closes)
            continue
        vals, gaps = [], []
        for day, px in closes:
            v = _value_at(per_share, day)
            vals.append(round(px / v, 4) if v and v > 0 else None)
            # why a day has no multiple: "neg" = loss / negative FCF, "na" = no usable figure
            gaps.append(None if (v and v > 0) else ("neg" if v is not None else "na"))
        out["series"][key] = vals
        out["series"][f"{key}_gap"] = gaps
        if key == "pe":
            first = closes[0][0]
            out["series"]["results"] = sorted({k.isoformat() for k, _ in per_share if k > first})
        if vals[-1] is not None:
            out[key] = _range(vals, vals[-1])
        else:
            latest = _value_at(per_share, closes[-1][0])
            out["notes"].append(f"{what} n/m ({'loss-making' if key == 'pe' else 'negative FCF'})"
                                if latest is not None else f"{what} n/a: latest period not usable")
    out["notes"] = _tidy_notes(out["notes"])
    return out


def _tidy_notes(notes: list[str]) -> list[str]:
    """One line per kind of gap ("P/E gap after Mar 2025, Sep 2025: no FX
    rate"), duplicates dropped, order kept."""
    import re
    grouped: dict[tuple[str, str], list[str]] = {}
    other: list[str] = []
    for n in notes:
        m = re.match(r"^(.+?) gap after (\w{3} \d{4}): (.+)$", n)
        if m:
            grouped.setdefault((m.group(1), m.group(3)), []).append(m.group(2))
        elif n not in other:
            other.append(n)
    out = []
    for (what, why), when in grouped.items():
        when = list(dict.fromkeys(when))
        shown = ", ".join(when[:3]) + (f" and {len(when) - 3} more" if len(when) > 3 else "")
        out.append(f"{what} gap after {shown}: {why}")
    return out + other


def _fx_lookup() -> FxLookup:
    cache: dict[str, object] = {}

    def lookup(frm: str, to: str, day: dt.date) -> Optional[float]:
        key = f"{frm}{to}"
        if key not in cache:
            try:
                cache[key] = eodhd.fx_series(frm, to, dt.date.today() - dt.timedelta(days=1200))
            except eodhd.EODHDError as exc:
                print(f"[ranges] FX {key} unavailable: {exc}", flush=True)
                cache[key] = None
        s = cache[key]
        if s is None or len(s) == 0:
            return None
        import pandas as pd
        upto = s[s.index <= pd.Timestamp(day)]
        return float(upto.iloc[-1]) if len(upto) else None

    return lookup


def range_payload(ticker: str, default_exchange: str = US) -> dict | None:
    """52-week ranges (and daily series) for one ticker, or None if EODHD
    can't price it. Cached per run. Tickers use Wally/Sally spelling
    (``PWH.AX``, ``RR.L``, ``POOL``)."""
    key = ticker.strip().upper()
    if key in _CACHE:
        return _CACHE[key]
    result = None
    try:
        sym = eodhd.symbol(key, default_exchange)
        prices = eodhd.eod(sym, dt.date.today() - dt.timedelta(days=372))
        fund = None
        try:
            fund = eodhd.fundamentals(sym)
        except eodhd.EODHDError as exc:
            print(f"[ranges] {key}: fundamentals unavailable ({exc})", flush=True)
        result = compute_ranges(prices, fund, eodhd.quote_currency(sym), _fx_lookup())
        result["symbol"] = sym
        print(f"[ranges] {key}: price={bool(result['price'])} pe={bool(result['pe'])} "
              f"pfcf={bool(result['pfcf'])} {'; '.join(result['notes'])}", flush=True)
    except Exception as exc:  # never let a range bar break an email
        print(f"[ranges] {key}: no ranges ({type(exc).__name__}: {exc})", flush=True)
    _CACHE[key] = result
    return result


def compact(ranges: dict | None) -> dict | None:
    """The ranges without the daily series, for JSON written to the dashboard."""
    if not ranges:
        return None
    return {k: v for k, v in ranges.items() if k != "series"}


# ── Rendering ────────────────────────────────────────────────────────────────

def _fmt(v: float, kind: str) -> str:
    if kind == "price":
        return f"{v:,.2f}" if v >= 1 else f"{v:.3f}"
    return f"{v:.1f}x" if v < 100 else f"{v:.0f}x"


def range_bar_html(r: dict | None, kind: str = "price", dark: bool = False, width: int = 120) -> str:
    """A tight 52-week range bar: current value, track with marker, low/high underneath.

    Marker colour: green in the bottom fifth of the range, red in the top fifth.
    """
    muted = "#94a3b8" if dark else "#6b7280"
    if not r:
        return f"<span style='color:{muted};font-size:10px'>n/a</span>"
    pos = float(r.get("position", 0.5))
    track = "#334155" if dark else "#d1d5db"
    text = "#e2e8f0" if dark else "#111827"
    mark = "#16a34a" if pos <= 0.2 else "#dc2626" if pos >= 0.8 else "#2563eb"
    left = max(0, min(100, round(pos * 100)))
    right = 100 - left
    seg = (f"<div style='height:3px;line-height:3px;font-size:0;background:{track}'>&nbsp;</div>")
    cell = "padding:0;vertical-align:middle;"
    left_td = f"<td style='{cell}width:{left}%'>{seg}</td>" if left else ""
    right_td = f"<td style='{cell}width:{right}%'>{seg}</td>" if right else ""
    tip = f"52w {LABELS.get(kind, '')}: {_fmt(r['low'], kind)} to {_fmt(r['high'], kind)}, now {_fmt(r['current'], kind)} ({left}% of range)"
    return (
        f"<table role='presentation' title='{tip}' cellpadding='0' cellspacing='0' border='0' "
        f"style='width:{width}px;border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;"
        f"font-size:10px;line-height:11px;margin:0'>"
        f"<tr><td style='padding:0 0 1px 0;color:{text};font-weight:bold;font-size:11px'>"
        f"{_fmt(r['current'], kind)}</td></tr>"
        f"<tr><td style='padding:0'><table role='presentation' cellpadding='0' cellspacing='0' border='0' "
        f"style='width:100%;border-collapse:collapse;height:9px'><tr>"
        f"{left_td}<td style='{cell}width:3px'><div style='width:3px;height:9px;line-height:9px;"
        f"font-size:0;background:{mark};border-radius:1px'>&nbsp;</div></td>{right_td}"
        f"</tr></table></td></tr>"
        f"<tr><td style='padding:1px 0 0 0'><table role='presentation' cellpadding='0' cellspacing='0' "
        f"border='0' style='width:100%;border-collapse:collapse'><tr>"
        f"<td style='padding:0;color:{muted};font-size:9px;text-align:left'>{_fmt(r['low'], kind)}</td>"
        f"<td style='padding:0;color:{muted};font-size:9px;text-align:right'>{_fmt(r['high'], kind)}</td>"
        f"</tr></table></td></tr></table>"
    )


def range_cells_html(ranges: dict | None, keys=("price", "pe"), dark: bool = False) -> str:
    """One <td> per metric, ready to drop into an existing table row."""
    style = "padding:4px 6px;vertical-align:middle"
    return "".join(
        f"<td style='{style}'>{range_bar_html((ranges or {}).get(k), k, dark=dark)}</td>" for k in keys
    )


def range_header_html(keys=("price", "pe")) -> str:
    return "".join(f"<th>{LABELS[k]}</th>" for k in keys)
