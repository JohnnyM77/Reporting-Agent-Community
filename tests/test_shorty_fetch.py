"""Shorty's ASIC short-position fetch/parse.

Pins the exact URL pattern and CSV header shape confirmed against the live
12-Oct-2026 report (RR20261012-001-SSDailyAggShortPos.csv), and the
backward / outward date-probing logic that finds "the most recent report"
and "the report closest to 1 July" without any index of available dates to
query directly.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest

import shorty_fetch as sf

SAMPLE_CSV = (
    "Product,Product Code,Reported Short Positions,Total Product in Issue,"
    "% of Total Product in Issue Reported as Short Positions\r\n"
    "DRONESHIELD LIMITED ORDINARY,DRO,150210887,925339724,16.23\r\n"
    "LOTUS RESOURCES LTD ORDINARY,LOT,85107764,547045342,15.56\r\n"
    "BHP GROUP LIMITED ORDINARY,BHP,35897910,371821214,1.23\r\n"
)


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_report_url_matches_confirmed_live_pattern():
    url = sf._report_url(dt.date(2026, 10, 12))
    assert url == "https://download.asic.gov.au/short-selling/RR20261012-001-SSDailyAggShortPos.csv"


def test_parse_csv_text_reads_confirmed_columns():
    rows = sf._parse_csv_text(SAMPLE_CSV)
    assert len(rows) == 3
    dro = next(r for r in rows if r.product_code == "DRO")
    assert dro.product == "DRONESHIELD LIMITED ORDINARY"
    assert dro.reported_short_positions == 150210887
    assert dro.total_product_in_issue == 925339724
    assert dro.pct_short == pytest.approx(16.23)


def test_parse_csv_text_rejects_changed_header_shape():
    """A header rename/reorder is a real problem, not something to guess a
    mapping for -- this is the same 'never invent, name the cap' rule the
    rest of the codebase applies to a changed data shape."""
    bad = "Code,Name,Short,Total,Pct\r\nDRO,DroneShield,1,2,3\r\n"
    with pytest.raises(sf.AsicFetchError):
        sf._parse_csv_text(bad)


def test_parse_num_strips_commas_and_percent():
    assert sf._parse_num("1,234,567") == 1234567.0
    assert sf._parse_num(" 16.23% ") == pytest.approx(16.23)


def test_fetch_report_returns_none_on_404():
    with patch.object(sf, "requests") as mock_requests:
        mock_requests.get.return_value = _Resp(404)
        assert sf.fetch_report(dt.date(2026, 10, 13)) is None


def test_fetch_report_parses_200():
    with patch.object(sf, "requests") as mock_requests:
        mock_requests.get.return_value = _Resp(200, SAMPLE_CSV)
        rows = sf.fetch_report(dt.date(2026, 10, 12))
        assert rows is not None
        assert len(rows) == 3


def test_find_most_recent_report_never_probes_the_future():
    """Today's/yesterday's report routinely doesn't exist (publication lag);
    the search must walk backward only and stop at the first hit."""
    calls = []

    def fake_fetch(d, log=sf._log):
        calls.append(d)
        return [sf.ShortRow("X", "X", 1, 2, 3.0)] if d == dt.date(2026, 10, 9) else None

    with patch.object(sf, "fetch_report", side_effect=fake_fetch):
        found_date, rows = sf.find_most_recent_report(
            today=dt.date(2026, 10, 12), max_back_days=10,
        )
    assert found_date == dt.date(2026, 10, 9)
    assert rows is not None
    # every probed date must be <= today -- never looked into the future
    assert all(d <= dt.date(2026, 10, 12) for d in calls)
    # probed in strictly decreasing order from today
    assert calls == sorted(calls, reverse=True)


def test_find_most_recent_report_gives_up_cleanly():
    with patch.object(sf, "fetch_report", return_value=None):
        found_date, rows = sf.find_most_recent_report(
            today=dt.date(2026, 10, 12), max_back_days=3,
        )
    assert found_date is None
    assert rows is None


def test_find_nearest_report_searches_outward_both_directions():
    """1 July 2026 is a Wednesday in this fixture's assumed calendar; make
    only 1 July itself missing and 2 July present -- nearest should pick
    the single day forward over anything further back."""
    target = dt.date(2026, 7, 1)

    def fake_fetch(d, log=sf._log):
        if d == dt.date(2026, 7, 2):
            return [sf.ShortRow("X", "X", 1, 2, 3.0)]
        return None

    with patch.object(sf, "fetch_report", side_effect=fake_fetch):
        found_date, rows = sf.find_nearest_report(target, max_radius_days=5)
    assert found_date == dt.date(2026, 7, 2)
    assert rows is not None


def test_find_nearest_report_prefers_closer_date_over_further_one():
    """30 June is 1 day before the target, 3 July is 2 days after -- the
    nearer one (by radius, not by direction) must win even though it's
    the backward candidate."""
    target = dt.date(2026, 7, 1)
    available = {dt.date(2026, 6, 30), dt.date(2026, 7, 3)}

    def fake_fetch(d, log=sf._log):
        return [sf.ShortRow("X", "X", 1, 2, 3.0)] if d in available else None

    with patch.object(sf, "fetch_report", side_effect=fake_fetch):
        found_date, _ = sf.find_nearest_report(target, max_radius_days=5)
    assert found_date == dt.date(2026, 6, 30)


def test_fy_start_date_before_and_after_july():
    assert sf.fy_start_date(dt.date(2026, 10, 17)) == dt.date(2026, 7, 1)
    assert sf.fy_start_date(dt.date(2026, 3, 1)) == dt.date(2025, 7, 1)
    assert sf.fy_start_date(dt.date(2026, 7, 1)) == dt.date(2026, 7, 1)
    assert sf.fy_start_date(dt.date(2026, 6, 30)) == dt.date(2025, 7, 1)


def test_rank_map_ranks_by_pct_descending():
    rows = sf._parse_csv_text(SAMPLE_CSV)
    ranks = sf.rank_map(rows)
    assert ranks["DRO"] == 1
    assert ranks["LOT"] == 2
    assert ranks["BHP"] == 3


def test_rows_by_code_first_occurrence_wins():
    rows = [
        sf.ShortRow("A", "DRO", 1, 2, 1.0),
        sf.ShortRow("B", "DRO", 3, 4, 2.0),
    ]
    by_code = sf.rows_by_code(rows)
    assert by_code["DRO"].product == "A"


def test_load_watchlist_universe_only_keeps_asx_tickers():
    """The watchlists mix in US/UK names (Nap Taker: AMD, MSFT; Cornerstone:
    AUTO, LSEG) which ASIC's ASX-only report can never cover -- only the
    literal .AX suffix marks a real ASX ticker."""
    universe, error = sf.load_watchlist_universe()
    assert error is None
    assert universe  # the real watchlists/ directory is non-trivial
    assert all(not t.endswith(".AX") for t in universe), "suffix must be stripped"
    # Known non-ASX names from the real watchlist files must never appear.
    for non_asx in ("AMD", "MSFT", "AMZN", "AUTO", "LSEG", "V", "MA"):
        assert non_asx not in universe


def test_load_watchlist_universe_dedupes_by_wally_priority_order():
    """A ticker carried by more than one standard list is attributed to
    the highest-priority one -- Income > JM > Aussie Tech > Cornerstone
    > Nap Taker, exactly STANDARD_WATCHLISTS' own order. BHP appears in
    income_watchlist.yaml (checked directly), so if it's also in a lower
    list it must still resolve to Income Watchlist."""
    from wally.watchlist_loader import load_watchlist
    income = load_watchlist("watchlists/income_watchlist.yaml")
    assert "BHP.AX" in income.tickers  # sanity-check the fixture assumption

    universe, error = sf.load_watchlist_universe()
    assert error is None
    assert universe.get("BHP") == income.name


def test_load_watchlist_universe_excludes_given_tickers():
    universe_full, _ = sf.load_watchlist_universe()
    assert universe_full  # must be non-empty for this to be a meaningful test
    some_ticker = next(iter(universe_full))
    universe_excluded, error = sf.load_watchlist_universe(exclude={some_ticker})
    assert error is None
    assert some_ticker not in universe_excluded
    assert len(universe_excluded) == len(universe_full) - 1


def test_load_watchlist_universe_degrades_on_total_load_failure(monkeypatch):
    """Every standard-list load failing must be a visible error, not a
    silently empty section -- same 'half-broken must never look clean'
    rule as the rest of Shorty."""
    import wally.watchlist_loader as loader

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(loader, "load_watchlist", _raise)
    universe, error = sf.load_watchlist_universe()
    assert universe == {}
    assert error and "could be loaded" in error.lower()


def test_clean_product_name_strips_asic_suffix_and_title_cases():
    assert sf.clean_product_name("DRONESHIELD LIMITED ORDINARY") == "Droneshield Limited"
    assert sf.clean_product_name("LENDLEASE GROUP FPO/UNITS STAPLED") == "Lendlease Group"
    assert sf.clean_product_name("PILBARA MINERALS LIMITED ORDINARY FULLY PAID") == "Pilbara Minerals Limited"


def test_clean_product_name_preserves_short_allcaps_acronyms():
    """BHP, CSL etc. read as ticker-like acronyms, not words that want
    sentence casing -- a plain .title() would turn BHP into 'Bhp'."""
    assert sf.clean_product_name("BHP GROUP LIMITED ORDINARY") == "BHP Group Limited"


def test_clean_product_name_handles_empty_input():
    assert sf.clean_product_name("") == ""
    assert sf.clean_product_name(None) == ""


def test_load_portfolio_tickers_excludes_etfs(tmp_path):
    yaml_text = """
asx:
  DRO: DroneShield Limited
  VAS: Vanguard Australian Shares Index ETF
etf_tickers:
  - VAS
"""
    path = tmp_path / "tickers.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    tickers = sf.load_portfolio_tickers(path)
    assert tickers == {"DRO": "DroneShield Limited"}
