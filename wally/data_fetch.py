"""Wally's market data. Every number comes from EODHD (shared/eodhd.py).

There is no second source and no fallback: a ticker EODHD cannot price
returns None / an empty series, and the caller reports it as missing.
Tickers arrive in Wally's Yahoo-style spelling (``NHC.AX``, ``RR.L``,
``POOL``) and are mapped to EODHD symbols here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from shared import eodhd
from shared.securities import US


@dataclass
class ValuationSnapshot:
    """Current valuation metrics for a ticker, from EODHD fundamentals.

    All fields may be None when EODHD does not carry the figure.
    Ratios (trailing_pe, forward_pe, ev_to_ebitda, price_to_sales) are plain
    multiples (e.g. 25.0 means 25×). fcf_yield and dividend_yield are
    expressed as decimals (e.g. 0.04 means 4%).
    """

    trailing_pe: Optional[float]
    forward_pe: Optional[float]
    ev_to_ebitda: Optional[float]
    price_to_sales: Optional[float]
    fcf_yield: Optional[float]
    dividend_yield: Optional[float]


@dataclass
class PriceSnapshot:
    ticker: str
    company_name: str
    current_price: float
    low_52w: float
    high_52w: float
    price_date: str = ""
    source: str = eodhd.SOURCE


def eodhd_symbol(ticker: str) -> str:
    """Wally ticker -> EODHD symbol. A bare code is US (Wally writes ASX as .AX)."""
    return eodhd.symbol(ticker, default_exchange=US)


def fetch_price_snapshot(ticker: str) -> Optional[PriceSnapshot]:
    try:
        sym = eodhd_symbol(ticker)
        summary = eodhd.price_summary(sym)
    except eodhd.EODHDError as e:
        print(f"[wally/data_fetch] {ticker}: no price from EODHD ({e})", flush=True)
        return None

    name = ticker
    try:
        name = (eodhd.fundamentals(sym).get("General") or {}).get("Name") or ticker
    except eodhd.EODHDError as e:
        print(f"[wally/data_fetch] {ticker}: company name unavailable ({e})", flush=True)

    if summary.low_52w <= 0:
        print(f"[wally/data_fetch] Invalid 52-week low ({summary.low_52w}) for {ticker}", flush=True)
        return None

    print(f"[wally/data_fetch] {ticker} ({sym}, EODHD close {summary.last_date}): "
          f"current={summary.last:.2f}, 52w low={summary.low_52w:.2f}, "
          f"52w high={summary.high_52w:.2f}", flush=True)
    return PriceSnapshot(
        ticker=ticker,
        company_name=str(name),
        current_price=summary.last,
        low_52w=summary.low_52w,
        high_52w=summary.high_52w,
        price_date=summary.last_date,
    )


def fetch_price_history_10y_monthly(ticker: str) -> pd.Series:
    try:
        start = dt.date.today() - dt.timedelta(days=3653)
        return eodhd.close_series(eodhd_symbol(ticker), start, period="m")
    except eodhd.EODHDError as e:
        print(f"[wally/data_fetch] {ticker}: no 10y monthly history from EODHD ({e})", flush=True)
        return pd.Series(dtype=float)


def fetch_price_history_10y_daily(ticker: str, csv_path: Path) -> Path:
    """Fetch 10-year daily OHLCV history from EODHD, save to CSV, and return the path.

    The CSV uses YYYYMMDD-formatted dates in the Date column, which matches
    the format expected by generate_asx_value_spreadsheet.
    """
    start = dt.date.today() - dt.timedelta(days=3653)
    df = eodhd.ohlcv_frame(eodhd_symbol(ticker), start)
    if df.empty:
        raise RuntimeError(f"No 10-year daily history from EODHD for {ticker}")
    df = df.dropna(subset=["Close"])
    df.index = pd.to_datetime(df.index).strftime("%Y%m%d")
    df.index.name = "Date"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path)
    return csv_path


def split_adjusted_closes(rows: list[dict]) -> list[tuple[dt.date, float]]:
    """Raw closes corrected for share splits only.

    EODHD's ``adjusted_close`` also strips dividends, which drags every old
    price down and would make a genuine multi-year low look ordinary. A split
    shows up as a step change in adjusted/raw between two rows (dividends
    move it a few per cent at most), so only steps over 25% are applied.
    """
    pts = []
    for r in rows:
        try:
            d = dt.date.fromisoformat(str(r["date"])[:10])
            c, a = float(r["close"]), float(r.get("adjusted_close") or r["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if c > 0 and a > 0:
            pts.append((d, c, a / c))
    pts.sort()
    factor = 1.0
    out: list[tuple[dt.date, float]] = []
    for i in range(len(pts) - 1, -1, -1):          # newest first: splits scale everything before them
        d, c, ratio = pts[i]
        out.append((d, c * factor))
        if i > 0:
            step = pts[i - 1][2] / ratio
            if step > 1.25 or step < 0.8:
                factor *= step
    return out[::-1]


def fetch_long_closes(ticker: str, years: int = 10) -> list[tuple[dt.date, float]]:
    """Split-adjusted daily closes for the last ``years`` years ([] if EODHD has none)."""
    try:
        start = dt.date.today() - dt.timedelta(days=round(365.25 * years) + 7)
        return split_adjusted_closes(eodhd.eod(eodhd_symbol(ticker), start))
    except eodhd.EODHDError as e:
        print(f"[wally/data_fetch] {ticker}: no {years}y history from EODHD ({e})", flush=True)
        return []


def fetch_valuation_snapshot(ticker: str) -> ValuationSnapshot:
    """Current valuation metrics from EODHD fundamentals.

    Returns a ValuationSnapshot with None for anything EODHD does not carry.
    """
    try:
        s = eodhd.snapshot(eodhd_symbol(ticker))
    except eodhd.EODHDError as e:
        print(f"[wally/data_fetch] {ticker}: no fundamentals from EODHD ({e})", flush=True)
        return ValuationSnapshot(None, None, None, None, None, None)
    return ValuationSnapshot(
        trailing_pe=s.trailing_pe,
        forward_pe=s.forward_pe,
        ev_to_ebitda=s.ev_to_ebitda,
        price_to_sales=s.price_to_sales,
        fcf_yield=s.fcf_yield,
        dividend_yield=s.dividend_yield,
    )
