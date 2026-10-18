from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict
from typing import Optional

from .config import LOW_THRESHOLD_PCT, MULTI_YEAR_HORIZONS
from shared.lows import multi_year_low as _multi_year_low
from .data_fetch import PriceSnapshot


@dataclass
class TickerScreenResult:
    ticker: str
    company_name: str
    current_price: float
    low_52w: float
    high_52w: float
    distance_to_low_pct: float
    below_high_pct: float
    flagged: bool
    near_low: bool = False
    target_price: Optional[float] = None
    below_target: bool = False
    distance_to_target_pct: Optional[float] = None
    error: Optional[str] = None
    # Multi-year low: the longest horizon (years) whose low the price is
    # within threshold of, e.g. 3 = "near its 3-year low". None = not checked
    # or not near any multi-year low.
    multi_year_low_years: Optional[int] = None
    multi_year_lows: Optional[dict] = None          # {"2": low, "3": low, ...} for horizons with full history
    ranges_52w: Optional[dict] = None               # shared.ranges.compact(): price / P/E / P/FCF

    @property
    def multi_year_low(self) -> bool:
        return bool(self.multi_year_low_years)

    def to_dict(self) -> dict:
        return asdict(self)


def multi_year_low(
    current: float,
    closes: list[tuple[dt.date, float]],
    today: dt.date,
    threshold_pct: float = LOW_THRESHOLD_PCT,
    horizons: tuple[int, ...] = MULTI_YEAR_HORIZONS,
) -> tuple[Optional[int], dict]:
    """Wally's multi-year low: horizons of 2 years and up (``shared.lows``)."""
    return _multi_year_low(current, closes, today, threshold_pct, tuple(h for h in horizons if h >= 2))


def screen_snapshot(
    snapshot: PriceSnapshot,
    threshold_pct: float = LOW_THRESHOLD_PCT,
    target_price: Optional[float] = None,
) -> TickerScreenResult:
    # Validate 52-week low data
    if snapshot.low_52w <= 0:
        return TickerScreenResult(
            ticker=snapshot.ticker,
            company_name=snapshot.company_name,
            current_price=snapshot.current_price,
            low_52w=snapshot.low_52w,
            high_52w=snapshot.high_52w,
            distance_to_low_pct=0.0,
            below_high_pct=0.0,
            flagged=False,
            target_price=target_price,
            error="Invalid 52w low",
        )

    current = snapshot.current_price
    distance_to_low_pct = ((current - snapshot.low_52w) / snapshot.low_52w) * 100
    below_high_pct = (
        ((snapshot.high_52w - current) / snapshot.high_52w) * 100
        if snapshot.high_52w > 0
        else 0.0
    )

    near_low = distance_to_low_pct <= threshold_pct

    below_target = False
    distance_to_target_pct: Optional[float] = None
    if target_price and target_price > 0:
        distance_to_target_pct = ((current - target_price) / target_price) * 100
        below_target = current <= target_price

    return TickerScreenResult(
        ticker=snapshot.ticker,
        company_name=snapshot.company_name,
        current_price=current,
        low_52w=snapshot.low_52w,
        high_52w=snapshot.high_52w,
        distance_to_low_pct=distance_to_low_pct,
        below_high_pct=below_high_pct,
        flagged=near_low or below_target,
        near_low=near_low,
        target_price=target_price,
        below_target=below_target,
        distance_to_target_pct=distance_to_target_pct,
    )
