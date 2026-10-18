"""Wally: multi-year-low flag, 52-week P/E and P/FCF in the email, price slider on the site.

Offline: no EODHD calls (price histories and ranges are built by hand)."""
import datetime as dt

from wally import email_report as E
from wally import main as M
from wally.data_fetch import split_adjusted_closes
from wally.screening import TickerScreenResult, multi_year_low
from dashboard.sections.wally import _range_slider, _wally_section

TODAY = dt.date(2026, 10, 6)


def _history(years: float, path):
    """Daily closes over ``years``; ``path(age_in_years)`` gives the price."""
    n = int(365.25 * years)
    return [(TODAY - dt.timedelta(days=i), path(i / 365.25)) for i in range(n, -1, -1)]


def test_horizon_is_the_longest_low_within_the_band():
    # Lowest price for 5 years is today's area; 7 years ago it was lower.
    hist = _history(10, lambda age: 10.0 if age > 6 else 20.0 if age > 0.02 else 10.4)
    yrs, lows = multi_year_low(10.4, hist, TODAY, threshold_pct=5.0, horizons=(2, 3, 5, 10))
    assert yrs == 10                          # within 5% of the 10-year low too (10.0)
    assert lows["2"] == 10.4 and lows["10"] == 10.0

    hist = _history(10, lambda age: 6.0 if age > 6 else 20.0 if age > 0.02 else 10.4)
    yrs, _ = multi_year_low(10.4, hist, TODAY, threshold_pct=5.0, horizons=(2, 3, 5, 10))
    assert yrs == 5                           # a 5-year low, not a 10-year one


def test_only_a_52_week_low_is_not_multi_year():
    hist = _history(10, lambda age: 8.0 if age > 1.5 else 20.0 if age > 0.02 else 12.0)
    yrs, lows = multi_year_low(12.0, hist, TODAY, threshold_pct=5.0, horizons=(2, 3, 5, 10))
    assert yrs is None and lows["2"] == 8.0


def test_short_history_never_claims_a_horizon_it_cannot_see():
    hist = _history(1.5, lambda age: 10.0)    # listed 18 months ago
    yrs, lows = multi_year_low(10.0, hist, TODAY, horizons=(2, 3))
    assert yrs is None and lows == {}


def test_split_adjustment_ignores_dividends_but_applies_splits():
    rows = [
        {"date": "2020-01-02", "close": 100.0, "adjusted_close": 45.0},   # pre 2-for-1 split
        {"date": "2020-01-03", "close": 100.0, "adjusted_close": 45.0},
        {"date": "2020-01-06", "close": 50.0, "adjusted_close": 45.0},    # split day
        {"date": "2021-01-04", "close": 50.0, "adjusted_close": 46.0},    # dividend steps: ignored
        {"date": "2022-01-04", "close": 50.0, "adjusted_close": 50.0},
    ]
    out = dict(split_adjusted_closes(rows))
    assert out[dt.date(2020, 1, 2)] == 50.0   # halved by the split, not cut by the dividends
    assert out[dt.date(2022, 1, 4)] == 50.0 and out[dt.date(2021, 1, 4)] == 50.0


def _row(t, years=None, ranges=None, near=True, below=False):
    return TickerScreenResult(
        ticker=t, company_name=f"{t} Ltd", current_price=10.0, low_52w=9.8, high_52w=15.0,
        distance_to_low_pct=2.0, below_high_pct=33.0, flagged=True, near_low=near,
        target_price=12.0, below_target=below, multi_year_low_years=years, ranges_52w=ranges,
    )


RANGES = {"price": {"low": 9.8, "high": 15.0, "current": 10.0, "position": 0.04},
          "pe": {"low": 12.0, "high": 20.0, "current": 13.0, "position": 0.125},
          "pfcf": None, "notes": ["P/FCF n/m (negative FCF)"]}


def test_email_shows_pe_and_pfcf_ranges_and_the_multi_year_trigger():
    html = E.build_html("JM Watch List", "2026-10-06", [], [_row("AAA.AX", 3, RANGES)], {})
    assert "52W P/E" in html and "52W P/FCF" in html
    assert "13.0x" in html and "12.0x" in html and "20.0x" in html
    assert ">n/m<" in html                     # negative FCF says so, not a blank
    assert "3Y LOW" in html and "Near 3-year low" in html
    for banned in ("display:flex", "display:grid", "<style", "class="):
        assert banned not in html
    plain = E.build_html("JM", "2026-10-06", [], [_row("BBB.AX")], {})
    assert "Near 52w low" in plain and ">n/a<" in plain


def test_multi_year_lows_sort_first():
    rows = [_row("A"), _row("B", 2), _row("C"), _row("D", 5)]
    assert [r.ticker for r in M._flag_order(rows)] == ["D", "B", "A", "C"]


def test_dashboard_slider_and_badge():
    s = _range_slider(9.8, 15.0, 10.0, 12.0)
    assert "left:4%" in s and "Buy price $12.00" in s and "$9.80" in s and "$15.00" in s
    assert "n/a" in _range_slider(None, 15.0, 10.0)
    card = _wally_section({"last_run": "2026-10-06T00:00:00", "watchlists": {"JM Watch List": {
        "total": 2, "flagged_count": 1, "flagged": [
            {"ticker": "AAA.AX", "company_name": "AAA Ltd", "current_price": 10.0, "low_52w": 9.8,
             "high_52w": 15.0, "distance_to_low_pct": 2.0, "near_low": True, "target_price": 12.0,
             "below_target": True, "multi_year_low_years": 3}]}}})
    assert "52W Range" in card and "3Y LOW" in card and "3y low + Buy price" in card
