"""Share price, share count and FX from EODHD (shared/eodhd.py), the one
market-data source every agent uses. Best-effort: any failure returns None and
the caller falls back to the model's sourced figures, labelled as NOT
verified against EODHD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from shared import eodhd

Log = Callable[[str], None]


@dataclass
class Quote:
    price: Optional[float] = None
    currency: Optional[str] = None
    shares_m: Optional[float] = None
    as_of: str = ""
    source: str = eodhd.SOURCE


def eodhd_symbol(ticker: str) -> str:
    """Bare codes are ASX (``PWH`` -> ``PWH.AU``)."""
    return eodhd.symbol(ticker)


def fetch_quote(ticker: str, log: Log = print) -> Quote:
    try:
        sym = eodhd_symbol(ticker)
        summary = eodhd.price_summary(sym)
    except eodhd.EODHDError as exc:
        log(f"[esther] EODHD price lookup failed for {ticker}: {exc}")
        return Quote(source="unavailable")
    shares = currency = None
    try:
        snap = eodhd.snapshot(sym)
        shares, currency = snap.shares_outstanding, snap.currency
    except eodhd.EODHDError as exc:
        log(f"[esther] EODHD share count unavailable for {ticker}: {exc}")
    return Quote(price=summary.last, currency=summary.currency or currency or "AUD",
                 shares_m=float(shares) / 1e6 if shares else None, as_of=summary.last_date)


def fx_rate(from_ccy: str, to_ccy: str, log: Log = print) -> Optional[float]:
    """Units of *to_ccy* per one unit of *from_ccy* (latest EODHD daily close)."""
    from_ccy, to_ccy = (from_ccy or "").upper(), (to_ccy or "").upper()
    if not from_ccy or not to_ccy or from_ccy == to_ccy:
        return 1.0
    try:
        return eodhd.fx_rate(from_ccy, to_ccy)[0]
    except eodhd.EODHDError as exc:
        log(f"[esther] EODHD FX lookup failed for {from_ccy}->{to_ccy}: {exc}")
        return None
