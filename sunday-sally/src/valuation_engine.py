from __future__ import annotations

from dataclasses import dataclass

from .pathing import ensure_repo_root_on_path

ensure_repo_root_on_path()

from shared import eodhd  # noqa: E402


@dataclass
class ValuationSnapshot:
    trailing_pe: float | None
    forward_pe: float | None
    enterprise_value: float | None
    ev_to_ebitda: float | None
    price_to_sales: float | None
    fcf_yield: float | None
    dividend_yield: float | None


def fetch_valuation_snapshot(exchange_ticker: str) -> ValuationSnapshot:
    """Current multiples from EODHD fundamentals; None for anything EODHD lacks."""
    try:
        s = eodhd.snapshot(eodhd.symbol(exchange_ticker))
    except eodhd.EODHDError as e:
        print(f"[sally] {exchange_ticker}: no fundamentals from EODHD ({e})", flush=True)
        return ValuationSnapshot(None, None, None, None, None, None, None)
    return ValuationSnapshot(
        trailing_pe=s.trailing_pe,
        forward_pe=s.forward_pe,
        enterprise_value=s.ev,
        ev_to_ebitda=s.ev_to_ebitda,
        price_to_sales=s.price_to_sales,
        fcf_yield=s.fcf_yield,
        dividend_yield=s.dividend_yield,
    )
