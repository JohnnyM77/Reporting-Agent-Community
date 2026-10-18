"""shorty_agent.py's row builders -- pure functions, no network/Playwright
needed to test them (Playwright is only ever imported lazily inside
_render_pdf, not at module level)."""

from __future__ import annotations

from shorty_fetch import ShortRow
from shorty_agent import _build_rows, _build_watchlist_rows


def test_watchlist_rows_get_company_name_from_the_asic_current_report():
    """ARB isn't in tickers.yaml (only portfolio tickers are), so its name
    has to come from somewhere else -- the ASIC report's own Product field
    for that ticker, cleaned up."""
    universe = {"ARB": "JM Watch List"}
    current_by_code = {"ARB": ShortRow("ARISTOCRAT LEISURE LIMITED ORDINARY", "ARB", 1, 2, 9.5)}
    rows = _build_watchlist_rows(universe, current_by_code, {"ARB": 3}, {}, {})
    assert len(rows) == 1
    assert rows[0].company == "Aristocrat Leisure Limited"
    assert rows[0].watchlist == "JM Watch List"


def test_watchlist_row_falls_back_to_baseline_report_for_name():
    """A ticker missing from the current report but present in the
    baseline one still gets a name -- either report's Product field will
    do. (XERO is 4 chars/all-caps, so the acronym-preserving cleanup
    deliberately leaves it as "XERO" rather than "Xero" -- same rule that
    keeps "BHP" from becoming "Bhp".)"""
    universe = {"XRO": "JM Watch List"}
    baseline_by_code = {"XRO": ShortRow("XERO LIMITED ORDINARY", "XRO", 1, 2, 6.5)}
    rows = _build_watchlist_rows(universe, {}, {}, baseline_by_code, {"XRO": 10})
    assert rows[0].company == "XERO Limited"


def test_watchlist_row_has_no_name_when_ticker_in_neither_report():
    """Never invent a name -- a ticker absent from both reports gets an
    empty company, same as it gets 'not reported' percentages."""
    universe = {"ZZZ": "JM Watch List"}
    rows = _build_watchlist_rows(universe, {}, {}, {}, {})
    assert rows[0].company == ""
    assert rows[0].current_pct is None


def test_holdings_rows_use_tickers_yaml_name_not_asic_product():
    """Portfolio holdings keep their curated tickers.yaml name -- never
    overwritten by whatever ASIC's Product field happens to say."""
    tickers = {"DRO": "DroneShield Limited"}
    current_by_code = {"DRO": ShortRow("DRONESHIELD LIMITED ORDINARY", "DRO", 1, 2, 16.23)}
    rows = _build_rows(tickers, current_by_code, {"DRO": 1}, {}, {})
    assert rows[0].company == "DroneShield Limited"
