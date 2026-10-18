"""shared/ranges.py + shared/range_chart.py: the 52-week P/E and P/FCF that
Sally puts in her email. Offline: statements and prices are hand-built in
the shape EODHD returns them (numbers as strings, half-year periods)."""

from __future__ import annotations

import datetime as dt

import pytest

from shared import ranges
from shared.range_chart import range_chart_html, render_range_chart


def _prices(start: str, closes: list[float]) -> list[dict]:
    d0 = dt.date.fromisoformat(start)
    return [{"date": (d0 + dt.timedelta(days=7 * i)).isoformat(), "close": c, "high": c, "low": c, "volume": 1}
            for i, c in enumerate(closes)]


def _fund(ni: dict, fcf: dict, shares: float = 100_000_000, history: dict | None = None,
          ccy: str = "AUD") -> dict:
    """ni / fcf = {period_end: value}; half-year periods like EODHD's ASX data."""
    q = {str(i): {"dateFormatted": d, "shares": shares} for i, d in enumerate(sorted(set(ni) | set(fcf)))}
    return {
        "General": {"CurrencyCode": ccy},
        "outstandingShares": {"quarterly": q},
        "Earnings": {"History": history or {}},
        "Financials": {
            "Income_Statement": {"currency_symbol": ccy,
                                 "quarterly": {d: {"date": d, "netIncome": str(v)} for d, v in ni.items()}},
            "Cash_Flow": {"currency_symbol": ccy,
                          "quarterly": {d: {"date": d, "freeCashFlow": str(v)} for d, v in fcf.items()}},
        },
    }


# PWH's real EODHD half-years (2026-10-05): 1H25+2H25 = FY25 9.77m, 1H26+2H26 = FY26 17.89m.
PWH_NI = {"2024-12-31": 4_084_000, "2025-06-30": 5_683_000, "2025-12-31": 5_661_000, "2026-06-30": 12_233_000}
PWH_FCF = {"2024-12-31": -4_918_000, "2025-06-30": -10_356_000, "2025-12-31": -2_210_000, "2026-06-30": 15_195_000}
PWH_HIST = {"2025-06-30": {"reportDate": "2025-08-11"}, "2025-12-31": {"reportDate": "2026-02-18"},
            "2026-06-30": {"reportDate": "2026-08-20"}}


def test_pe_is_ttm_from_half_years_stepping_on_release_dates():
    prices = _prices("2025-10-03", [8.0] * 52 + [10.0])          # last close 2026-10-02
    r = ranges.compute_ranges(prices, _fund(PWH_NI, PWH_FCF, history=PWH_HIST), "AUD")
    # Today: TTM = 1H26 + 2H26 = 17.894m / 100m shares = 17.894c -> 10.00 / 0.17894
    assert r["pe"]["current"] == pytest.approx(10.0 / 0.17894, rel=1e-3)
    # Before the 20 Aug 2026 release the in-force TTM was 2H25 + 1H26 = 11.344c
    s = r["series"]
    i = s["dates"].index("2026-08-14")
    assert s["pe"][i] == pytest.approx(8.0 / 0.11344, rel=1e-3)
    assert "2026-08-20" in s["results"]


def test_negative_fcf_is_a_labelled_gap_not_a_number():
    prices = _prices("2025-10-03", [8.0] * 53)
    r = ranges.compute_ranges(prices, _fund(PWH_NI, PWH_FCF, history=PWH_HIST), "AUD")
    s = r["series"]
    i = s["dates"].index("2026-08-14")             # TTM FCF then: -2.21m + -10.36m... negative
    assert s["pfcf"][i] is None and s["pfcf_gap"][i] == "neg"
    assert r["pfcf"]["current"] == pytest.approx(8.0 / (12_985_000 / 100_000_000), rel=1e-3)


def test_loss_today_means_no_current_pe():
    ni = {"2025-12-31": -5_000_000, "2026-06-30": -1_000_000}
    r = ranges.compute_ranges(_prices("2025-10-03", [5.0] * 53), _fund(ni, {}), "AUD")
    assert r["pe"] is None
    assert any("loss-making" in n for n in r["notes"])


def test_usd_reporter_converted_at_release_date_fx():
    fund = _fund({"2025-12-31": 50_000_000, "2026-06-30": 50_000_000}, {}, ccy="USD")
    fund["General"]["CurrencyCode"] = "AUD"
    seen = []

    def fx(frm, to, day):
        seen.append((frm, to))
        return 1.5
    r = ranges.compute_ranges(_prices("2025-10-03", [30.0] * 53), fund, "AUD", fx)
    assert ("USD", "AUD") in seen
    assert r["pe"]["current"] == pytest.approx(30.0 / (1.0 * 1.5), rel=1e-3)   # 100m/100m = US$1.00 EPS


def test_lse_pence_against_gbp_statements():
    fund = _fund({"2025-12-31": 50_000_000, "2026-06-30": 50_000_000}, {}, ccy="GBP")
    r = ranges.compute_ranges(_prices("2025-10-03", [450.0] * 53), fund, "GBX")   # 450p
    assert r["pe"]["current"] == pytest.approx(450.0 / 100.0, rel=1e-3)          # EPS 100p -> 4.5x


def test_rounded_eps_actual_is_not_used():
    # EODHD's Earnings.History epsActual for PWH is 0.06 + 0.06 = 12c; the statements say 17.9c.
    hist = {k: {**v, "epsActual": 0.06} for k, v in PWH_HIST.items()}
    r = ranges.compute_ranges(_prices("2025-10-03", [10.0] * 53), _fund(PWH_NI, PWH_FCF, history=hist), "AUD")
    assert r["pe"]["current"] == pytest.approx(10.0 / 0.17894, rel=1e-3)        # ~55.9x, not 83x


def test_chart_renders_small_png_and_email_block(tmp_path):
    pytest.importorskip("matplotlib")
    r = ranges.compute_ranges(_prices("2025-10-03", [8.0 + i * 0.03 for i in range(53)]),
                              _fund(PWH_NI, PWH_FCF, history=PWH_HIST), "AUD")
    png = render_range_chart(r, tmp_path / "x.png", "PWH")
    assert png and png.stat().st_size < 120_000
    html = range_chart_html("ranges_pwh", "PWH", r)
    assert "cid:ranges_pwh" in html
    for banned in ("<style", "class=", "display:flex", "display:grid"):
        assert banned not in html


def test_nothing_to_plot_returns_none(tmp_path):
    assert render_range_chart(None, tmp_path / "x.png") is None
    assert render_range_chart({"series": {"dates": []}}, tmp_path / "x.png") is None


def test_range_payload_never_raises(monkeypatch):
    ranges._CACHE.clear()
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    assert ranges.range_payload("PWH.AX") is None


def test_gap_notes_are_collapsed_into_one_line():
    notes = [f"P/E gap after {m} {y}: no FX rate" for y in range(1994, 2000) for m in ("Mar", "Sep")]
    out = ranges._tidy_notes(notes + ["P/FCF n/m (negative FCF)", "P/FCF n/m (negative FCF)"])
    assert len(out) == 2 and out[0].startswith("P/E gap after Mar 1994, Sep 1994, Mar 1995 and 9 more")
