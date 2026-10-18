from __future__ import annotations

from dataclasses import dataclass

from .pathing import ensure_repo_root_on_path

ensure_repo_root_on_path()

from shared import eodhd  # noqa: E402


@dataclass
class PriceData:
    ticker: str
    company_name: str
    current_price: float
    high_52w: float
    low_52w: float
    distance_to_high: float
    market_cap: float | None
    price_date: str = ""
    source: str = eodhd.SOURCE


def fetch_price_data(exchange_ticker: str, raw_ticker: str) -> PriceData | None:
    """Last close and 52-week range from EODHD. None (never a guess) when EODHD has no price."""
    try:
        sym = eodhd.symbol(exchange_ticker)
        summary = eodhd.price_summary(sym)
    except eodhd.EODHDError as e:
        print(f"[sally] {raw_ticker}: no price from EODHD ({e})", flush=True)
        return None

    high_52w, current = summary.high_52w, summary.last
    distance_to_high = (high_52w - current) / high_52w if high_52w > 0 else 1.0

    name, market_cap = raw_ticker, None
    try:
        snap = eodhd.snapshot(sym)
        name, market_cap = snap.name or raw_ticker, snap.market_cap
    except eodhd.EODHDError as e:
        print(f"[sally] {raw_ticker}: fundamentals unavailable ({e})", flush=True)

    return PriceData(
        ticker=raw_ticker,
        company_name=str(name),
        current_price=current,
        high_52w=high_52w,
        low_52w=summary.low_52w,
        distance_to_high=distance_to_high,
        market_cap=market_cap,
        price_date=summary.last_date,
    )
