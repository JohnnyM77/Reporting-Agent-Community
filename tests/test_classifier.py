"""Archetype classifier + sync, offline (no EODHD)."""
import datetime as dt
from pathlib import Path

import yaml

from shared import archetype_sync, classifier
from shared.classifier import Features, classify_features, suggest_archetype

RULES = classifier.load_rules()


def feat(**kw):
    base = dict(ticker="T", company="T Ltd", sector="Industrials", sector_source="GICS", industry="X",
                roic=0.12, revenue_cagr=0.06, loss_years=0, loss_years_5=0, years_of_history=10,
                eps_yoy_stdev=0.4, eps_ttm=1.0, eps_3y_avg=0.9, eps_7y_avg=0.8, eps_7y_years=7,
                median_pe_10y=40.0, net_cash=False, net_debt_to_ebitda=1.0)
    base.update(kw)
    return Features(**base)


def test_sector_rules_first():
    assert suggest_archetype(feat(sector="Materials"), RULES)[0] == "cyclical"
    assert suggest_archetype(feat(sector="Financials", industry="Banks"), RULES)[0] == "financial"
    assert suggest_archetype(feat(sector="Real Estate"), RULES)[0] == "property_infra"
    assert suggest_archetype(feat(sector="Industrials", industry="Transportation Infrastructure"), RULES)[0] == "property_infra"
    assert suggest_archetype(feat(eps_ttm=-0.2), RULES)[0] == "early_growth"


def test_quality_split():
    assert suggest_archetype(feat(roic=0.35, revenue_cagr=0.15), RULES)[0] == "compounder"
    assert suggest_archetype(feat(roic=0.14, revenue_cagr=0.06), RULES)[0] == "quality_steady"
    assert suggest_archetype(feat(roic=0.12, revenue_cagr=0.01, sector="Consumer Staples"), RULES)[0] == "defensive_mature"


def test_modifiers_and_base():
    c = classify_features(feat(roic=0.30, net_cash=True, eps_yoy_stdev=0.1), RULES, archetype="quality_steady")
    # 18 + 2 (ROIC) + 2 (net cash) + 2 (stable) = 24
    assert c.raw_multiple == 24 and c.buy_multiple == 24
    c = classify_features(feat(roic=0.05, net_debt_to_ebitda=3.5, loss_years=1), RULES,
                          archetype="quality_steady", structural_headwind=True)
    assert c.raw_multiple == 18 - 8


def test_guardrails():
    c = classify_features(feat(roic=0.30, net_cash=True, eps_yoy_stdev=0.1, median_pe_10y=20.0), RULES, archetype="compounder")
    assert c.raw_multiple == 31 and c.buy_multiple == 20.0 and any("median" in g for g in c.guardrails)
    c = classify_features(feat(roic=0.02, loss_years=2, median_pe_10y=3.0), RULES, archetype="cyclical")
    assert c.buy_multiple == 6   # floor wins
    c = classify_features(feat(roic=0.30, net_cash=True, eps_yoy_stdev=0.1, median_pe_10y=90.0), RULES, archetype="compounder")
    assert c.buy_multiple == 31
    rules = yaml.safe_load(yaml.safe_dump(RULES)); rules["archetypes"]["compounder"]["base_multiple"] = 40
    assert classify_features(feat(median_pe_10y=90.0), rules, archetype="compounder").buy_multiple == 35  # ceiling


def test_override_always_wins():
    c = classify_features(feat(median_pe_10y=8.0), RULES, archetype="compounder",
                          override_multiple=22, override_reason="owner call")
    assert c.buy_multiple == 22 and c.override_reason == "owner call"


def test_financials_skip_roic_and_debt():
    c = classify_features(feat(sector="Financials", roic=0.02, net_debt_to_ebitda=9.0), RULES)
    assert c.archetype == "financial"
    assert {m.name for m in c.modifiers} <= {"stability", "structural_headwind"}


def test_no_pe_line_archetypes():
    c = classify_features(feat(sector="Real Estate", dividend_yield=0.05), RULES)
    assert c.buy_multiple is None and c.alt_metric == "dividend_yield" and c.alt_metric_value == 0.05


def test_eps_basis_and_implied_price():
    c = classify_features(feat(), RULES, archetype="defensive_mature")   # 15x, 3yr avg
    assert c.eps_basis == "avg_3y" and c.implied_buy_price == round(c.buy_multiple * 0.9, 2)


def test_unclassifiable_is_not_silent():
    a, conf, why = suggest_archetype(Features(ticker="X", error="EODHDNotCovered: nope"), RULES)
    assert a == classifier.UNCLASSIFIED and conf == 0 and "nope" in why[0]


def test_confirmed_entry_supplies_archetype():
    f = feat(roic=0.35, revenue_cagr=0.15)   # would suggest compounder
    c = classifier.classify_with_entry(f, RULES, {"status": "confirmed", "archetype": "cyclical"})
    assert c.archetype == "cyclical" and not c.suggested and c.confidence == 1.0
    c = classifier.classify_with_entry(f, RULES, {"status": "auto", "archetype": "cyclical"})
    assert c.archetype == "compounder"


def _wl(d: Path, name, tickers):
    (d / f"{name}.yaml").write_text(yaml.safe_dump({"name": name.title(), "tickers": tickers}))


def _fake(t):
    return classifier.classify_features(feat(ticker=t), RULES)


def test_sync_adds_deactivates_and_never_touches_confirmed(tmp_path):
    wl = tmp_path / "wl"; wl.mkdir()
    _wl(wl, "a", ["AAA.AX", "BBB.AX"]); _wl(wl, "b", ["BBB.AX", "CCC"])
    path = tmp_path / "entries.yaml"
    kw = dict(entries_path=path, classify_fn=_fake, today=dt.date(2026, 10, 6), log=lambda m: None)
    mem = archetype_sync.watchlist_membership(wl, None)
    assert mem["BBB.AX"] == ["A", "B"]
    out = archetype_sync.sync_archetypes(membership=mem, **kw)
    assert set(out["added"]) == {"AAA.AX", "BBB.AX", "CCC"}
    e = archetype_sync.load_entries(path)
    e["AAA.AX"].update(status="confirmed", archetype="cyclical", override_multiple=9, override_reason="mine")
    archetype_sync.save_entries(e, path)

    _wl(wl, "a", ["BBB.AX"])      # AAA leaves every list
    mem = archetype_sync.watchlist_membership(wl, None)
    out = archetype_sync.sync_archetypes(membership=mem, **{**kw, "today": dt.date(2027, 6, 1)})
    e = archetype_sync.load_entries(path)
    assert out["deactivated"] == ["AAA.AX"] and e["AAA.AX"]["active"] is False
    assert (e["AAA.AX"]["status"], e["AAA.AX"]["archetype"], e["AAA.AX"]["override_multiple"]) == ("confirmed", "cyclical", 9)
    assert out["added"] == []
    assert e["BBB.AX"]["last_classified"] == "2027-06-01"       # stale auto entry refreshed


def test_pending_and_email_block(tmp_path):
    path = tmp_path / "e.yaml"
    mem = {"AAA.AX": ["A"]}
    out = archetype_sync.sync_archetypes(entries_path=path, membership=mem, classify_fn=_fake, log=lambda m: None)
    pend = archetype_sync.pending_confirmation(out["entries"])
    html = archetype_sync.new_tickers_html(pend)
    assert "New tickers needing confirmation" in html and "AAA.AX" in html
    for banned in ("<style", "class=", "display:flex", "display:grid"):
        assert banned not in html
    archetype_sync.mark_emailed(["AAA.AX"], path)
    assert archetype_sync.pending_confirmation(archetype_sync.load_entries(path)) == []


def test_every_watchlist_ticker_is_covered_by_membership():
    mem = archetype_sync.watchlist_membership()
    assert len(mem) > 100 and "BHP.AX" in mem


class _FakeEodhd:
    """Minimal stand-in for shared.eodhd, enough for _fill_features."""
    class _Snap:
        trailing_pe = None; trailing_eps = None; dividend_yield = None; price_to_sales = None; fcf_yield = None
    class _Px:
        last = 12.5

    def snapshot(self, sym, fund): return self._Snap()
    def price_summary(self, sym, today): return self._Px()
    def annual_eps(self, sym, fund):
        return [{"eps": 1.0, "fiscal_end": f"{y}-06-30", "release_date": None} for y in range(2018, 2026)]
    def close_series(self, *a, **k):
        import pandas as pd
        return pd.Series(dtype=float)
    def known_from(self, r): return r["fiscal_end"]


def test_price_and_ttm_fallback_are_filled():
    f = Features(ticker="T", quote_currency="AUD")
    fund = {"General": {"Name": "T", "Type": "Common Stock", "CurrencyCode": "AUD", "GicSector": "Health Care"},
            "Financials": {"Income_Statement": {"yearly": {}}, "Balance_Sheet": {"yearly": {}}}}
    classifier._fill_features(f, "T.AU", fund, dt.date(2026, 10, 6), RULES, _FakeEodhd())
    assert f.price == 12.5 and f.eps_ttm == 1.0 and any("latest annual EPS used" in n for n in f.notes)
