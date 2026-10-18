from __future__ import annotations

from dataclasses import dataclass

import datetime as dt

import pandas as pd

from .pathing import ensure_repo_root_on_path

ensure_repo_root_on_path()

from shared import eodhd  # noqa: E402


@dataclass
class HistoricalValuationSummary:
    pe_3y_avg: float | None
    pe_5y_avg: float | None
    pe_10y_avg: float | None
    ev_ebitda_avg: float | None
    valuation_percentile: float | None
    notes: list[str]


def _approx_pe_series(exchange_ticker: str) -> pd.Series:
    """Monthly PE = EODHD month-end close / the reported annual EPS in force
    that month (EODHD income statements). Months before the first positive
    EPS, or while the latest EPS is a loss, are left out rather than filled."""
    try:
        sym = eodhd.symbol(exchange_ticker)
        eps_rows = eodhd.annual_eps(sym)
        prices = eodhd.close_series(sym, dt.date.today() - dt.timedelta(days=3653), period="m")
    except eodhd.EODHDError as e:
        print(f"[sally] {exchange_ticker}: historical PE unavailable ({e})", flush=True)
        return pd.Series(dtype=float)
    if prices.empty or not eps_rows:
        return pd.Series(dtype=float)

    released = sorted((dt.date.fromisoformat(eodhd.known_from(r)), r["eps"]) for r in eps_rows)
    values = {}
    for ts, close in prices.items():
        in_force = [eps for d, eps in released if d <= ts.date()]
        if in_force and in_force[-1] > 0:
            values[ts] = close / in_force[-1]
    return pd.Series(values, dtype=float).sort_index()


def summarize_history(exchange_ticker: str, current_trailing_pe: float | None, current_ev_ebitda: float | None) -> HistoricalValuationSummary:
    notes: list[str] = []
    pe_series = _approx_pe_series(exchange_ticker)

    def _window_avg(years: int) -> float | None:
        if pe_series.empty:
            return None
        cutoff = pe_series.index.max() - pd.DateOffset(years=years)
        sub = pe_series[pe_series.index >= cutoff]
        return float(sub.mean()) if not sub.empty else None

    pe_3 = _window_avg(3)
    pe_5 = _window_avg(5)
    pe_10 = _window_avg(10)

    percentile = None
    if current_trailing_pe and not pe_series.empty:
        percentile = float((pe_series <= current_trailing_pe).mean())

    if pe_series.empty:
        notes.append("Historical PE unavailable: EODHD has no positive reported EPS history for this ticker.")
    if current_ev_ebitda is None:
        notes.append("EV/EBITDA context unavailable from source feed.")

    ev_avg = current_ev_ebitda
    return HistoricalValuationSummary(
        pe_3y_avg=pe_3,
        pe_5y_avg=pe_5,
        pe_10y_avg=pe_10,
        ev_ebitda_avg=ev_avg,
        valuation_percentile=percentile,
        notes=notes,
    )


def valuation_ratio(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline in (None, 0):
        return None
    return float(current / baseline)


def percentile_bucket(percentile: float | None) -> str:
    if percentile is None:
        return "unknown"
    if percentile >= 0.9:
        return "top_10_percent"
    if percentile >= 0.8:
        return "top_20_percent"
    if percentile >= 0.5:
        return "median_or_above"
    return "below_average"
