"""Multi-year lows: is today's price near its 2-, 3-, 5- or 10-year low?

Shared by Wally (the multi-year-low flag) and Sally (the line at the top of
the value-wedge chart). Pure functions on (date, close) pairs; no fetching.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional


def multi_year_low(
    current: float,
    closes: list[tuple[dt.date, float]],
    today: dt.date,
    threshold_pct: float = 5.0,
    horizons: tuple[int, ...] = (2, 3, 5, 10),
) -> tuple[Optional[int], dict]:
    """Longest horizon (years) whose lowest close the price is within
    ``threshold_pct`` of, and the low for each horizon the history covers.

    A horizon only counts when the history really reaches back that far
    (first close within 30 days of the horizon start): a stock listed 18
    months ago has no 2-year low, rather than a flattering one.
    """
    pts = sorted((d, c) for d, c in closes if c and c > 0)
    if not pts or not current or current <= 0:
        return None, {}
    first = pts[0][0]
    lows: dict[str, float] = {}
    best = None
    for yrs in sorted(horizons):
        start = today - dt.timedelta(days=round(365.25 * yrs))
        if first > start + dt.timedelta(days=30):
            break
        window = [c for d, c in pts if d >= start]
        if not window:
            continue
        low = min(window)
        lows[str(yrs)] = round(low, 4)
        if (current - low) / low * 100 <= threshold_pct:
            best = yrs
    return best, lows


def lowest_since(current: float, closes: list[tuple[dt.date, float]], today: dt.date,
                 skip_days: int = 14) -> Optional[dt.date]:
    """The last date (before the past ``skip_days``) the stock closed at or
    below today's price. None = never, in the history given."""
    cutoff = today - dt.timedelta(days=skip_days)
    hit = None
    for d, c in sorted(closes):
        if d < cutoff and c <= current:
            hit = d
    return hit
