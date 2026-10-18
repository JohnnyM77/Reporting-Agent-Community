"""shared/eodhd.py: symbols, derived figures, and the "no guessing" rules.

Every test stubs the HTTP layer (``eodhd._get``), so nothing touches the
network. The fixture rows are shaped like real EODHD responses (PWH.AU,
checked 2026-10-05): numbers arrive as strings in the financial statements,
dividend yield is a fraction, and outstandingShares is keyed "0", "1", ...
"""

from __future__ import annotations

import datetime as dt

import pytest

from shared import eodhd


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    eodhd.clear_cache()
    monkeypatch.setenv("EODHD_API_TOKEN", "test-token")
    yield
    eodhd.clear_cache()


def _fake_get(responses: dict):
    calls = []

    def get(path, params=None, **kw):
        calls.append((path, dict(params or {})))
        for prefix, value in responses.items():
            if path.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value
        raise eodhd.EODHDError(f"EODHD {path}: not found (404)")

    get.calls = calls
    return get


PWH_FUND = {
    "General": {"Code": "PWH", "Name": "PWR Holdings Ltd", "CurrencyCode": "AUD", "UpdatedAt": "2026-10-04"},
    "Highlights": {"MarketCapitalization": 1005741184, "DividendYield": 0.008, "DilutedEpsTTM": 0.18},
    "Valuation": {"TrailingPE": 55.5556, "ForwardPE": 42.1941, "EnterpriseValue": 1089841197,
                  "EnterpriseValueEbitda": 26.7479, "PriceSalesTTM": 5.8908},
    "SharesStats": {"SharesOutstanding": 100574122},
    "Earnings": {"History": {"2025-06-30": {"reportDate": "2025-08-11", "date": "2025-06-30"}}},
    "outstandingShares": {"quarterly": {
        "0": {"date": "2025-Q2", "dateFormatted": "2025-06-30", "shares": 100563900},
        "1": {"date": "2024-Q2", "dateFormatted": "2024-06-30", "shares": 100484100},
    }},
    "Financials": {
        "Income_Statement": {"currency_symbol": "AUD", "yearly": {
            "2024-06-30": {"date": "2024-06-30", "netIncome": "24805000.00",
                           "netIncomeApplicableToCommonShares": "24805000.00", "currency_symbol": "AUD"},
            "2025-06-30": {"date": "2025-06-30", "netIncome": "9767000.00",
                           "netIncomeApplicableToCommonShares": "9767000.00", "currency_symbol": "AUD"},
            "2020-06-30": {"date": "2020-06-30", "netIncome": None, "currency_symbol": "AUD"},
        }},
        "Cash_Flow": {"yearly": {"2025-06-30": {"date": "2025-06-30", "freeCashFlow": "20114818.00"}}},
        "Balance_Sheet": {"yearly": {}},
    },
}


class TestSymbols:
    @pytest.mark.parametrize("raw, default, want", [
        ("PWH", "ASX", "PWH.AU"),
        ("pwh.ax", "ASX", "PWH.AU"),
        ("ASX:ABB", "ASX", "ABB.AU"),
        ("PWH.AU", "ASX", "PWH.AU"),
        ("RR.", "ASX", "RR.LSE"),
        ("RR.L", "US", "RR.LSE"),
        ("POOL", "US", "POOL.US"),
        ("BRK.B", "US", "BRK-B.US"),
        ("SHOP.TO", "US", "SHOP.TO"),
        ("USDAUD.FOREX", "ASX", "USDAUD.FOREX"),
    ])
    def test_maps_every_spelling_to_eodhd(self, raw, default, want):
        assert eodhd.symbol(raw, default) == want

    @pytest.mark.parametrize("raw", ["D05.SI", "SGX:D05", "AIR.NZ", "2914.T"])
    def test_exchanges_eodhd_lacks_are_refused_not_borrowed(self, raw):
        with pytest.raises(eodhd.EODHDNotCovered):
            eodhd.symbol(raw)

    def test_lse_is_quoted_in_pence(self):
        assert eodhd.quote_currency("RR.LSE") == "GBX"
        assert eodhd.quote_currency("PWH.AU") == "AUD"


class TestTransport:
    def test_no_token_raises_instead_of_fetching(self, monkeypatch):
        monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
        monkeypatch.delenv("EODHD_API_KEY", raising=False)
        with pytest.raises(eodhd.EODHDNotConfigured):
            eodhd.eod("PWH.AU")

    def test_token_never_appears_in_errors(self, monkeypatch):
        import urllib.error

        def boom(*a, **k):
            raise urllib.error.URLError("proxy refused https://eodhd.com/api/eod/X?api_token=test-token")

        monkeypatch.setattr(eodhd.urllib.request, "urlopen", boom)
        monkeypatch.setattr(eodhd.time, "sleep", lambda s: None)
        with pytest.raises(eodhd.EODHDError) as exc:
            eodhd.eod("PWH.AU")
        assert "test-token" not in str(exc.value)


class TestPrices:
    def test_price_summary_uses_raw_closes_and_drops_flat_candles(self, monkeypatch):
        today = dt.date(2026, 10, 5)
        rows = [
            {"date": "2025-09-01", "close": 99.0, "adjusted_close": 50.0, "volume": 10},  # > 1y ago
            {"date": "2025-12-01", "close": 8.0, "adjusted_close": 7.0, "volume": 10},
            {"date": "2026-03-01", "close": 1.0, "adjusted_close": 1.0, "volume": 0},     # flat candle
            {"date": "2026-10-02", "close": 12.0, "adjusted_close": 11.0, "volume": 10},
            {"date": "2026-10-03", "close": 10.0, "adjusted_close": 9.5, "volume": 10},
        ]
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/eod/": rows}))
        p = eodhd.price_summary("PWH.AU", today=today)
        assert (p.last, p.prev, p.last_date) == (10.0, 12.0, "2026-10-03")
        assert (p.low_52w, p.high_52w) == (8.0, 12.0)
        assert p.currency == "AUD" and p.source == "EODHD"

    def test_no_prices_is_an_error_not_a_number(self, monkeypatch):
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/eod/": []}))
        with pytest.raises(eodhd.EODHDError):
            eodhd.price_summary("PWH.AU")

    def test_fx_keeps_zero_volume_rows(self, monkeypatch):
        rows = [{"date": "2026-10-05", "close": 1.4405, "volume": 0}]
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/eod/USDAUD.FOREX": rows}))
        assert eodhd.fx_rate("USD", "AUD") == (1.4405, "2026-10-05")


class TestFundamentals:
    def test_snapshot_reads_documented_fields(self, monkeypatch):
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": PWH_FUND}))
        s = eodhd.snapshot("PWH.AU")
        assert s.name == "PWR Holdings Ltd"
        assert s.trailing_pe == pytest.approx(55.5556)
        assert s.forward_pe == pytest.approx(42.1941)
        assert s.ev_to_ebitda == pytest.approx(26.7479)
        assert s.dividend_yield == pytest.approx(0.008)          # a fraction, as EODHD sends it
        assert s.fcf_yield == pytest.approx(20114818 / 1005741184)
        assert s.shares_outstanding == 100574122

    def test_missing_fields_stay_none(self, monkeypatch):
        bare = {"General": {"Name": "X"}}
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": bare}))
        s = eodhd.snapshot("X.AU")
        assert s.trailing_pe is None and s.fcf_yield is None and s.dividend_yield is None

    def test_annual_eps_is_net_income_over_shares_with_release_date(self, monkeypatch):
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": PWH_FUND}))
        rows = eodhd.annual_eps("PWH.AU")
        assert [r["fiscal_end"] for r in rows] == ["2024-06-30", "2025-06-30"]  # 2020 had no net income
        fy25 = rows[-1]
        assert fy25["eps"] == pytest.approx(9767000 / 100563900)  # 9.71c, matches PWH's reported FY25
        assert fy25["release_date"] == "2025-08-11"
        assert rows[0]["release_date"] is None                   # unknown, not invented
        assert eodhd.known_from(rows[0]) == "2024-08-30"          # usable from the 2-month deadline
        assert eodhd.known_from(fy25) == "2025-08-11"

    def test_report_date_on_or_before_year_end_is_ignored(self, monkeypatch):
        # BHP FY2003-FY2013: EODHD's "reportDate" equals the year end, which
        # would make each result public on the day the year closed.
        import copy
        fund = copy.deepcopy(PWH_FUND)
        fund["Earnings"]["History"]["2024-06-30"] = {"reportDate": "2024-06-30"}
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": fund}))
        fy24 = eodhd.annual_eps("PWH.AU")[0]
        assert fy24["release_date"] is None
        assert eodhd.known_from(fy24) == "2024-08-30"

    @staticmethod
    def _shares_fund(years: dict) -> dict:
        """{year_end: (net_income, outstandingShares, balance-sheet shares)}"""
        inc, q, bs = {}, {}, {}
        for i, (d, (ni, os_, bsh)) in enumerate(sorted(years.items())):
            inc[d] = {"date": d, "netIncome": str(ni), "currency_symbol": "GBP"}
            if os_:
                q[str(i)] = {"dateFormatted": d, "shares": os_}
            if bsh:
                bs[d] = {"commonStockSharesOutstanding": str(bsh)}
        return {"General": {"Name": "X"}, "outstandingShares": {"quarterly": q},
                "Financials": {"Income_Statement": {"yearly": inc}, "Balance_Sheet": {"yearly": bs}}}

    # Rolls-Royce exactly as EODHD has it (checked 2026-10-05).
    RR = {
        "2017-12-31": (3382000000, 1843000000, 5361802320),
        "2018-12-31": (-2401000000, 1869000000, 5417168757),
        "2019-12-31": (-1315000000, 5626960000, 5548302857),
        "2020-12-31": (-3170000000, 8368000000, 5987000000),
        "2021-12-31": (120000000, 8368000000, 8352000000),
        "2022-12-31": (-1269000000, 8367600000, 8349000000),
    }

    def test_rolls_royce_bad_share_years_are_not_used(self, monkeypatch):
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": self._shares_fund(self.RR)}))
        used = [r["fiscal_end"][:4] for r in eodhd.annual_eps("RR.LSE")]
        # 2017-2018: the sources disagree (1.8bn vs 5.4bn); 2019: one source
        # jumps +201%, the other +2% (this is the year that read -23p for a
        # -69p loss); 2020: 8.4bn vs 6.0bn. 2021 on, both agree.
        assert used == ["2021", "2022"]
        why = {r["fiscal_end"][:4]: r.get("rejected") for r in eodhd.annual_eps("RR.LSE", include_rejected=True)}
        assert "disagree" in why["2018"] and "disagree" in why["2020"]
        assert "disagree" in why["2019"] or "inconsistently" in why["2019"]

    def test_inconsistent_jump_is_caught_even_when_sources_agree_that_year(self, monkeypatch):
        # Each year the two counts are within 20% of each other, but one
        # doubles (+100%) while the other rises 43%: not a story both tell.
        years = {"2018-12-31": (100, 1000, 1190), "2019-12-31": (100, 2000, 1700)}
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": self._shares_fund(years)}))
        why = {r["fiscal_end"][:4]: r.get("rejected") for r in eodhd.annual_eps("X.LSE", include_rejected=True)}
        assert why["2018"] is None
        assert "inconsistently" in why["2019"]

    def test_a_real_rights_issue_confirmed_by_both_sources_is_kept(self, monkeypatch):
        years = {"2019-12-31": (-1315000000, 1930000000, 1930000000),
                 "2020-12-31": (-3170000000, 8368000000, 8352000000)}
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": self._shares_fund(years)}))
        rows = eodhd.annual_eps("RR.LSE")
        assert [r["fiscal_end"][:4] for r in rows] == ["2019", "2020"]
        assert rows[0]["eps"] == pytest.approx(-0.681, abs=0.001)   # the reported -68p-ish, not -23p

    def test_single_source_jump_is_not_used(self, monkeypatch):
        years = {"2018-12-31": (100, 1000, None), "2019-12-31": (100, 3000, None)}
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": self._shares_fund(years)}))
        assert [r["fiscal_end"][:4] for r in eodhd.annual_eps("X.LSE")] == ["2018"]

    def test_dividends_by_year_uses_unadjusted_amounts(self, monkeypatch):
        divs = [
            {"date": "2025-03-13", "value": 0.02, "unadjustedValue": 0.02},
            {"date": "2025-09-18", "value": 0.02, "unadjustedValue": 0.02},
            {"date": "2026-03-02", "value": 0.03, "unadjustedValue": 0.03},
        ]
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/div/": divs}))
        assert eodhd.dividends_by_year("PWH.AU") == pytest.approx({"2025": 0.04, "2026": 0.03})


class TestAgentsHaveNoFallback:
    def test_wally_value_chart_refuses_to_invent_prices(self, monkeypatch):
        from wally.value_chart_builder import get_price_data

        monkeypatch.setattr(eodhd, "_get", _fake_get({"/eod/": eodhd.EODHDError("EODHD /eod/X: HTTP 402")}))
        with pytest.raises(RuntimeError, match="EODHD"):
            get_price_data({"ticker": "POOL"})

    def test_wally_snapshot_none_when_eodhd_has_no_price(self, monkeypatch):
        from wally.data_fetch import fetch_price_snapshot

        monkeypatch.setattr(eodhd, "_get", _fake_get({"/eod/": []}))
        assert fetch_price_snapshot("PWH.AX") is None

    def test_wally_fundamentals_cache_from_old_source_is_rebuilt(self, tmp_path, monkeypatch):
        from wally import fundamentals_store as fs

        monkeypatch.setattr(fs, "_store_path", lambda t: tmp_path / f"{fs._slug(t)}.json")
        monkeypatch.chdir(tmp_path)  # no valuations/ overrides here
        fs.save("PWH.AX", {"last_updated": str(dt.date.today()), "annual_eps_cents": {"2025": 99.0},
                           "sources": {"2025": "yfinance"}})
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/fundamentals/": PWH_FUND, "/div/": []}))
        out = fs.get_fundamentals("PWH.AX")
        assert out["annual_eps_cents"]["2025"] == pytest.approx(9.71, abs=0.01)  # yfinance's 99c is gone
        assert out["eps_release_dates"] == {"2024": "2024-08-30", "2025": "2025-08-11"}
        assert fs.load("PWH.AX")["provider"] == "eodhd"
        assert fs.load("PWH.AX")["provider_version"] == fs.PROVIDER_VERSION

    def test_harry_prices_come_from_eodhd(self, monkeypatch):
        from hindsight.prices import EODHDPrices

        rows = [{"date": "2026-10-02", "close": 11.0, "volume": 5}, {"date": "2026-10-03", "close": 10.0, "volume": 5}]
        get = _fake_get({"/eod/PWH.AU": rows})
        monkeypatch.setattr(eodhd, "_get", get)
        assert EODHDPrices().recent(["PWH", "ZZZ"]) == {"PWH": {"last": 10.0, "prev": 11.0, "date": "2026-10-03"}}

    def test_esther_quote_from_eodhd(self, monkeypatch):
        from esther import market

        rows = [{"date": dt.date.today().isoformat(), "close": 10.5, "volume": 5}]
        monkeypatch.setattr(eodhd, "_get", _fake_get({"/eod/": rows, "/fundamentals/": PWH_FUND}))
        q = market.fetch_quote("PWH")
        assert (q.price, q.currency, q.source) == (10.5, "AUD", "EODHD")
        assert q.shares_m == pytest.approx(100.574122)


# ---------------------------------------------------------------------------
# debt_profile — the prior-leverage baseline for Bob's capital/debt-raise card
# ---------------------------------------------------------------------------

def _fund_with_bs(quarterly=None, yearly=None, ebitda=None, inc_yearly=None, ccy="USD"):
    fin = {"Balance_Sheet": {"quarterly": quarterly or {}, "yearly": yearly or {}}}
    if inc_yearly is not None:
        fin["Income_Statement"] = {"yearly": inc_yearly}
    return {
        "General": {"CurrencyCode": ccy},
        "Highlights": {"EBITDA": ebitda} if ebitda is not None else {},
        "Financials": fin,
    }


def test_debt_profile_prefers_newest_sheet_and_computes_ratios():
    fund = _fund_with_bs(
        quarterly={"2026-06-30": {"shortLongTermDebtTotal": "12300000000", "cash": "2300000000",
                                  "netDebt": "9900000000", "totalStockholderEquity": "15500000000"}},
        yearly={"2025-06-30": {"shortLongTermDebtTotal": "10000000000", "cash": "2000000000",
                               "totalStockholderEquity": "15000000000"}},
        ebitda=5_000_000_000,
    )
    p = eodhd.debt_profile("CSL.AU", fund=fund)
    assert p.period == "quarterly" and p.as_of == "2026-06-30"   # newest wins
    assert p.gross_debt == 12.3e9 and p.net_debt == 9.9e9 and p.total_equity == 15.5e9
    assert abs(p.net_debt_to_ebitda - 9.9e9 / 5.0e9) < 1e-9
    assert abs(p.gearing - 9.9e9 / 15.5e9) < 1e-9
    assert p.currency == "USD"


def test_debt_profile_falls_back_to_split_debt_cash_and_income_ebitda():
    fund = _fund_with_bs(
        yearly={"2025-06-30": {"shortTermDebt": "100000000", "longTermDebt": "400000000",
                               "cashAndEquivalents": "100000000", "totalStockholderEquity": "2000000000"}},
        inc_yearly={"2025-06-30": {"ebitda": "300000000"}},
    )
    p = eodhd.debt_profile("X.AU", fund=fund)
    assert p.gross_debt == 5e8          # 1e8 + 4e8
    assert p.net_debt == 4e8            # gross - cash (netDebt absent)
    assert p.ebitda == 3e8              # from income statement, Highlights empty
    assert abs(p.net_debt_to_ebitda - 4e8 / 3e8) < 1e-9


def test_debt_profile_raises_when_no_balance_sheet():
    with pytest.raises(eodhd.EODHDError):
        eodhd.debt_profile("X.AU", fund=_fund_with_bs())
