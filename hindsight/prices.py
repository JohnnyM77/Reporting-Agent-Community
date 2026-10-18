"""Price data from EODHD (shared/eodhd.py), the one market-data source every
agent uses.

Wally's ``fetch_price_snapshot`` only returns a one-year snapshot, which is
not enough for "daily move" or "since purchase", so this is a thin sibling
rather than a reuse. Every failure returns None; a missing price never
stops a run, it just means a gate that needs it cannot fire.
"""

from __future__ import annotations

PRICE_SOURCE = "EODHD"


class PriceProvider:
    def recent(self, tickers: list[str]) -> dict[str, dict]:
        """``{ticker: {"last": float, "prev": float, "date": str}}`` for bare ASX tickers."""
        raise NotImplementedError

    def current(self, ticker: str) -> float | None:
        return (self.recent([ticker]).get(ticker) or {}).get("last")


class StaticPrices(PriceProvider):
    def __init__(self, data: dict[str, dict] | None = None):
        self.data = data or {}

    def recent(self, tickers):
        return {t: self.data[t] for t in tickers if t in self.data}


class EODHDPrices(PriceProvider):
    def __init__(self):
        self._cache: dict[str, dict] = {}

    def recent(self, tickers):
        import datetime as dt

        from shared import eodhd

        failed = 0
        for t in tickers:
            if t in self._cache:
                continue
            try:
                rows = eodhd.eod(eodhd.symbol(t), dt.date.today() - dt.timedelta(days=14))
            except eodhd.EODHDError:
                failed += 1
                continue
            closes = [float(r["close"]) for r in rows]
            if closes:
                self._cache[t] = {"last": closes[-1], "prev": closes[-2] if len(closes) > 1 else None,
                                  "date": rows[-1]["date"]}
        if failed:
            # Counts only: Actions logs on this public repo are public.
            print(f"[hindsight] EODHD price fetch failed for {failed} ticker(s); their price gates will not fire")
        return {t: self._cache[t] for t in tickers if t in self._cache}
