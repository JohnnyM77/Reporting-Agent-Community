"""Valuation archetype classifier.

Every buy multiple in the repo comes from here, driven by
``config/valuation_archetypes.yaml``. Never hard-code a multiple elsewhere.

Two layers:
  * ``features_from_eodhd`` turns EODHD data (via ``shared/eodhd.py``, the only
    market-data source) into plain numbers. Offline-testable: pass ``fund`` in.
  * ``classify_features`` applies the rules: sector rules first, then quality
    metrics, then the +/-2x modifiers and the guardrails.

The classifier only *suggests*. A ticker entry in ``config/ticker_archetypes.yaml``
with ``status: confirmed`` supplies the archetype (and any override) and the
classifier then only works out the modifiers and guardrails.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml

RULES_PATH = Path(__file__).resolve().parents[1] / "config" / "valuation_archetypes.yaml"
UNCLASSIFIED = "unclassified"

_RULES_CACHE: dict[str, dict] = {}


def load_rules(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else RULES_PATH
    key = str(p)
    if key not in _RULES_CACHE:
        _RULES_CACHE[key] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return _RULES_CACHE[key]


def archetype_label(rules: dict, name: str) -> str:
    return ((rules.get("archetypes") or {}).get(name) or {}).get("label") or name


def eps_basis_label(rules: dict, basis: str) -> str:
    return ((rules.get("eps_bases") or {}).get(basis) or {}).get("label") or basis


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Features:
    """Plain numbers the rules need. Any figure EODHD does not carry is None."""
    ticker: str = ""
    symbol: str = ""
    company: str = ""
    quote_currency: Optional[str] = None
    security_type: str = "Common Stock"
    sector: str = ""            # GICS sector, else EODHD sector
    industry: str = ""          # GICS group/industry text, else EODHD industry
    sector_source: str = ""     # "GICS" | "EODHD" | ""
    roic: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    net_cash: Optional[bool] = None
    revenue_cagr: Optional[float] = None
    loss_years: Optional[int] = None          # loss years in the last stability_years
    loss_years_5: Optional[int] = None
    years_of_history: int = 0
    eps_yoy_stdev: Optional[float] = None
    eps_ttm: Optional[float] = None
    eps_3y_avg: Optional[float] = None
    eps_7y_avg: Optional[float] = None
    eps_7y_years: int = 0
    median_pe_10y: Optional[float] = None
    current_pe: Optional[float] = None
    price: Optional[float] = None
    price_to_book: Optional[float] = None
    dividend_yield: Optional[float] = None
    price_to_sales: Optional[float] = None
    fcf_yield: Optional[float] = None
    notes: list[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class Modifier:
    name: str
    delta: float
    reason: str


@dataclass
class Classification:
    ticker: str
    archetype: str
    suggested: bool                     # True: auto-suggested; False: supplied by a confirmed entry
    confidence: float
    reasons: list[str]
    base_multiple: Optional[float]
    modifiers: list[Modifier]
    raw_multiple: Optional[float]       # base + modifiers, before guardrails
    buy_multiple: Optional[float]       # final, after guardrails or override
    guardrails: list[str]
    median_pe_10y: Optional[float]
    eps_basis: str
    eps_value: Optional[float]          # the EPS the multiple applies to, in the quote currency
    implied_buy_price: Optional[float]
    override_reason: str = ""
    alt_metric: Optional[str] = None
    alt_metric_value: Optional[float] = None
    features: Optional[Features] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("features", None)
        return d

    def modifiers_text(self) -> str:
        return "; ".join(f"{m.delta:+g}x {m.reason}" for m in self.modifiers) or "none"


# ---------------------------------------------------------------------------
# Feature extraction (EODHD)
# ---------------------------------------------------------------------------

def _num(v: object) -> Optional[float]:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _years(d: dict) -> list[str]:
    return sorted(d or {})


def _roic_by_year(fund: dict) -> list[float]:
    """NOPAT / invested capital per year, oldest first. NOPAT = EBIT x (1 - tax rate)."""
    fin = fund.get("Financials") or {}
    inc = (fin.get("Income_Statement") or {}).get("yearly") or {}
    bs = (fin.get("Balance_Sheet") or {}).get("yearly") or {}
    out = []
    for d in _years(inc):
        r, b = inc[d] or {}, bs.get(d) or {}
        ebit = _num(r.get("ebit"))
        if ebit is None:
            ebit = _num(r.get("operatingIncome"))
        equity = _num(b.get("totalStockholderEquity"))
        debt = _num(b.get("shortLongTermDebtTotal"))
        if debt is None:
            debt = (_num(b.get("shortTermDebt")) or 0) + (_num(b.get("longTermDebt")) or 0)
        cash = _num(b.get("cash"))
        if cash is None:
            cash = _num(b.get("cashAndEquivalents")) or 0
        if ebit is None or equity is None:
            continue
        pretax, tax = _num(r.get("incomeBeforeTax")), _num(r.get("incomeTaxExpense"))
        rate = 0.30
        if pretax and pretax > 0 and tax is not None:
            rate = min(max(tax / pretax, 0.0), 0.35)
        ic = equity + debt - cash
        if ic > 0:
            out.append(ebit * (1 - rate) / ic)
    return out


def _revenue_cagr(fund: dict) -> Optional[float]:
    inc = ((fund.get("Financials") or {}).get("Income_Statement") or {}).get("yearly") or {}
    rev = [(d, _num((inc[d] or {}).get("totalRevenue"))) for d in _years(inc)]
    rev = [(d, v) for d, v in rev if v and v > 0]
    for n in (5, 3):
        if len(rev) >= n + 1:
            start, end = rev[-(n + 1)][1], rev[-1][1]
            return (end / start) ** (1 / n) - 1
    return None


def _loss_years(fund: dict, window: int) -> tuple[Optional[int], int]:
    inc = ((fund.get("Financials") or {}).get("Income_Statement") or {}).get("yearly") or {}
    ni = []
    for d in _years(inc):
        v = _num((inc[d] or {}).get("netIncome"))
        if v is None:
            v = _num((inc[d] or {}).get("netIncomeApplicableToCommonShares"))
        if v is not None:
            ni.append(v)
    if not ni:
        return None, 0
    recent = ni[-window:]
    return sum(1 for v in recent if v < 0), len(ni)


def _eps_yoy_stdev(eps: list[float]) -> Optional[float]:
    moves = [math.log(b / a) for a, b in zip(eps, eps[1:]) if a > 0 and b > 0]
    return statistics.pstdev(moves) if len(moves) >= 4 else None


def _stmt_currency(fund: dict) -> Optional[str]:
    inc = (fund.get("Financials") or {}).get("Income_Statement") or {}
    c = inc.get("currency_symbol") or (fund.get("General") or {}).get("CurrencyCode")
    c = (c or "").strip().upper()
    return "GBP" if c == "GBX" else (c or None)


def _median_pe(sym: str, eps_rows: list[dict], quote_ccy: Optional[str], stmt_ccy: Optional[str],
               years: int, today: dt.date, eodhd) -> tuple[Optional[float], Optional[str]]:
    """Median of month-end price / EPS-in-force over ``years``. EPS counts from its release date."""
    if not eps_rows:
        return None, "no EPS history for a median P/E"
    start = today - dt.timedelta(days=365 * years + 31)
    closes = eodhd.close_series(sym, start, today, period="m")
    if len(closes) < 24:
        return None, f"only {len(closes)} monthly prices for a median P/E"
    fx = None
    q = "GBP" if quote_ccy == "GBX" else quote_ccy
    pence = quote_ccy == "GBX"
    if q and stmt_ccy and q != stmt_ccy:
        try:
            fx = eodhd.fx_series(stmt_ccy, q, start, today)
        except Exception as e:  # noqa: BLE001
            return None, f"median P/E skipped: no {stmt_ccy}->{q} FX ({e})"
        if len(fx) == 0:
            return None, f"median P/E skipped: no {stmt_ccy}->{q} FX"
    known = sorted(((eodhd.known_from(r), r["eps"]) for r in eps_rows))
    pes = []
    for ts, px in closes.items():
        day = ts.date().isoformat()
        eps = None
        for kd, ev in known:
            if kd <= day:
                eps = ev
            else:
                break
        if eps is None or eps <= 0:
            continue
        if fx is not None:
            idx = fx.index.searchsorted(ts, side="right") - 1
            if idx < 0:
                continue
            eps = eps * float(fx.iloc[idx])
        price = px / 100.0 if pence else px
        pes.append(price / eps)
    if len(pes) < 24:
        return None, f"only {len(pes)} usable months for a median P/E"
    return float(statistics.median(pes)), None


def features_from_eodhd(ticker: str, *, today: Optional[dt.date] = None,
                        rules: Optional[dict] = None, fund: Optional[dict] = None) -> Features:
    """Fetch and compute everything the rules need for one ticker. Never raises:
    a failure comes back in ``Features.error``."""
    from shared import eodhd
    from shared.securities import US

    rules = rules or load_rules()
    today = today or dt.date.today()
    feat = Features(ticker=ticker)
    try:
        sym = eodhd.symbol(ticker, default_exchange=US)
        feat.symbol = sym
        feat.quote_currency = eodhd.quote_currency(sym)
        fund = fund if fund is not None else eodhd.fundamentals(sym)
    except Exception as e:  # noqa: BLE001
        feat.error = f"{type(e).__name__}: {e}"
        return feat

    try:
        return _fill_features(feat, sym, fund, today, rules, eodhd)
    except Exception as e:  # noqa: BLE001
        feat.error = f"{type(e).__name__}: {e}"
        return feat


def _fill_features(feat: Features, sym: str, fund: dict, today: dt.date, rules: dict, eodhd) -> Features:
    g = fund.get("General") or {}
    feat.company = g.get("Name") or ""
    feat.security_type = g.get("Type") or "Common Stock"
    if g.get("GicSector") or g.get("GicGroup"):
        feat.sector, feat.sector_source = g.get("GicSector") or "", "GICS"
        feat.industry = " | ".join(x for x in (g.get("GicGroup"), g.get("GicIndustry"), g.get("GicSubIndustry")) if x)
    elif g.get("Sector") or g.get("Industry"):
        feat.sector, feat.industry, feat.sector_source = g.get("Sector") or "", g.get("Industry") or "", "EODHD"
    if feat.security_type != "Common Stock":
        return feat

    mods = rules.get("modifiers") or {}
    window = int(mods.get("stability_years", 10))
    snap = eodhd.snapshot(sym, fund)
    feat.current_pe = snap.trailing_pe
    feat.eps_ttm = snap.trailing_eps
    feat.dividend_yield = snap.dividend_yield
    feat.price_to_sales = snap.price_to_sales
    feat.fcf_yield = snap.fcf_yield
    feat.price_to_book = _num((fund.get("Valuation") or {}).get("PriceBookMRQ"))
    try:
        feat.price = eodhd.price_summary(sym, today).last
    except Exception as e:  # noqa: BLE001
        feat.notes.append(f"no price from EODHD ({e})")

    roics = _roic_by_year(fund)
    if roics:
        feat.roic = statistics.median(roics[-3:])
    feat.revenue_cagr = _revenue_cagr(fund)
    feat.loss_years, feat.years_of_history = _loss_years(fund, window)
    feat.loss_years_5, _ = _loss_years(fund, 5)

    fin = fund.get("Financials") or {}
    bs = (fin.get("Balance_Sheet") or {}).get("yearly") or {}
    inc = (fin.get("Income_Statement") or {}).get("yearly") or {}
    if bs:
        b = bs[max(bs)] or {}
        nd = _num(b.get("netDebt"))
        if nd is None:
            debt, cash = _num(b.get("shortLongTermDebtTotal")), _num(b.get("cash"))
            nd = debt - cash if debt is not None and cash is not None else None
        ebitda = _num((inc.get(max(inc)) or {}).get("ebitda")) if inc else None
        if nd is not None:
            feat.net_cash = nd < 0
            if ebitda and ebitda > 0:
                feat.net_debt_to_ebitda = nd / ebitda
            elif nd > 0:
                feat.net_debt_to_ebitda = float("inf")

    eps_rows = eodhd.annual_eps(sym, fund)
    eps = [r["eps"] for r in eps_rows]
    feat.eps_yoy_stdev = _eps_yoy_stdev(eps[-window:])
    # Annual EPS is in the statement currency; convert once at today's FX to the quote currency.
    stmt_ccy = _stmt_currency(fund)
    q = "GBP" if feat.quote_currency == "GBX" else feat.quote_currency
    scale = 1.0
    if q and stmt_ccy and q != stmt_ccy:
        try:
            scale = eodhd.fx_rate(stmt_ccy, q)[0]
            feat.notes.append(f"EPS converted {stmt_ccy}->{q} at today's rate")
        except Exception as e:  # noqa: BLE001
            feat.notes.append(f"EPS currency {stmt_ccy} vs price {q}: no FX ({e}); averages not converted")
    if feat.quote_currency == "GBX":
        scale *= 100.0
    if eps:
        n3, n7 = eps[-3:], eps[-7:]
        feat.eps_3y_avg = statistics.fmean(n3) * scale
        feat.eps_7y_avg = statistics.fmean(n7) * scale
        feat.eps_7y_years = len(n7)
        if (feat.eps_ttm is None or feat.eps_ttm <= 0) and eps[-1] > 0:
            # EODHD Highlights TTM EPS is missing or unusable (CSL, a USD reporter): use the latest reported year.
            feat.notes.append(f"EODHD TTM EPS {feat.eps_ttm}: latest annual EPS used")
            feat.eps_ttm = eps[-1] * scale
    feat.median_pe_10y, why = _median_pe(sym, eps_rows, feat.quote_currency, stmt_ccy,
                                         int((rules.get("guardrails") or {}).get("median_years", 10)),
                                         today, eodhd)
    if why:
        feat.notes.append(why)
    return feat


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _matches(text: str, needles: list[str]) -> bool:
    t = (text or "").lower()
    return any(n.lower() in t for n in needles or [])


def _sector_archetype(feat: Features, rules: dict) -> Optional[str]:
    sr = (rules.get("classifier") or {}).get("sector_rules") or {}
    for arch in ("property_infra", "financial", "cyclical"):   # most specific first
        spec = sr.get(arch) or {}
        if _matches(feat.sector, spec.get("sectors")) or _matches(feat.industry, spec.get("industries")):
            return arch
    return None


def _near(value: Optional[float], threshold: float, margin: float) -> bool:
    return value is not None and threshold and abs(value - threshold) <= margin * abs(threshold)


def suggest_archetype(feat: Features, rules: dict) -> tuple[str, float, list[str]]:
    """(archetype, confidence, reasons). Sector rules first, then quality metrics."""
    c = rules.get("classifier") or {}
    margin = float(c.get("borderline_margin", 0.15))
    reasons: list[str] = []

    if feat.error:
        return UNCLASSIFIED, 0.0, [f"no EODHD data: {feat.error}"]
    if feat.security_type != "Common Stock":
        return UNCLASSIFIED, 0.0, [f"{feat.security_type}, not a company: no earnings multiple applies"]

    sector_arch = _sector_archetype(feat, rules)
    if sector_arch:
        conf = 0.90 if feat.sector_source == "GICS" else 0.85
        reasons.append(f"{feat.sector_source or 'sector'} sector '{feat.sector}' -> {sector_arch}")
        if _matches(feat.industry, (c.get("low_confidence_industries") or {}).get(sector_arch)):
            conf -= 0.30
            reasons.append(f"industry '{feat.industry}' is an awkward fit for {sector_arch}: check")
        if sector_arch in ("cyclical", "financial") and (feat.eps_ttm is None or feat.eps_ttm <= 0):
            conf -= 0.30
            reasons.append("TTM EPS negative or missing: may be pre-profit (early_growth)")
        if feat.years_of_history < 5:
            conf -= 0.10
            reasons.append(f"only {feat.years_of_history} years of statements")
        return sector_arch, max(round(conf, 2), 0.1), reasons

    if feat.eps_ttm is None or feat.eps_ttm <= 0:
        conf = 0.65 if feat.years_of_history >= 3 else 0.50
        reasons.append("EPS negative or missing -> early_growth")
        return "early_growth", conf, reasons

    conf = 0.80 if feat.sector_source == "GICS" else 0.65
    cp, qs = c.get("compounder") or {}, c.get("quality_steady") or {}
    roic, g = feat.roic, feat.revenue_cagr
    if roic is None:
        conf -= 0.20
        reasons.append("ROIC not computable")
    if g is None:
        conf -= 0.10
        reasons.append("revenue growth not computable")
    if feat.years_of_history < 5:
        conf -= 0.10
        reasons.append(f"only {feat.years_of_history} years of statements")

    compounder = (roic is not None and roic >= cp.get("roic_min", 0.20)
                  and g is not None and g >= cp.get("revenue_cagr_min", 0.08)
                  and (feat.loss_years_5 or 0) <= cp.get("max_loss_years_in_5", 0))
    if compounder:
        arch = "compounder"
        reasons.append(f"ROIC {roic:.0%} and revenue growth {g:.0%} a year clear the compounder bar")
        if _near(roic, cp["roic_min"], margin) or _near(g, cp["revenue_cagr_min"], margin):
            conf -= 0.15
            reasons.append("close to the compounder threshold")
    else:
        quality = (roic is not None and roic >= qs.get("roic_min", 0.10)
                   and g is not None and g >= qs.get("revenue_cagr_min", 0.04))
        defensive = _matches(feat.sector, c.get("defensive_sectors"))
        if quality and not (defensive and g < cp.get("revenue_cagr_min", 0.08) and roic < cp.get("roic_min", 0.20)):
            arch = "quality_steady"
            reasons.append(f"ROIC {roic:.0%}, revenue growth {g:.0%} a year")
        elif quality and defensive:
            arch = "defensive_mature"
            reasons.append(f"defensive sector '{feat.sector}', growth {g:.0%} a year")
        else:
            arch = "defensive_mature"
            reasons.append("below the quality bar" + (f" (ROIC {roic:.0%})" if roic is not None else "")
                           + (f", growth {g:.0%}" if g is not None else ""))
            if not defensive:
                conf -= 0.10
                reasons.append("not a defensive sector: could be a weak business or a cyclical")
        for val, thr in ((roic, qs.get("roic_min", 0.10)), (g, qs.get("revenue_cagr_min", 0.04)),
                         (roic, cp.get("roic_min", 0.20)), (g, cp.get("revenue_cagr_min", 0.08))):
            if _near(val, thr, margin):
                conf -= 0.15
                reasons.append("close to an archetype threshold")
                break
    return arch, max(round(conf, 2), 0.1), reasons


def _modifiers(arch: str, feat: Features, rules: dict, structural_headwind: bool) -> list[Modifier]:
    m = rules.get("modifiers") or {}
    step = float(m.get("step", 2))
    skip = (m.get("skip_for") or {}).get(arch) or []
    out: list[Modifier] = []
    if "roic" not in skip and feat.roic is not None:
        if feat.roic > m.get("roic_high", 0.20):
            out.append(Modifier("roic", +step, f"ROIC {feat.roic:.0%} above {m.get('roic_high', 0.20):.0%}"))
        elif feat.roic < m.get("roic_low", 0.08):
            out.append(Modifier("roic", -step, f"ROIC {feat.roic:.0%} below {m.get('roic_low', 0.08):.0%}"))
    if "net_debt" not in skip:
        if m.get("net_cash", True) and feat.net_cash:
            out.append(Modifier("net_debt", +step, "net cash"))
        elif (feat.net_debt_to_ebitda is not None
              and feat.net_debt_to_ebitda > m.get("net_debt_to_ebitda_max", 2.5)):
            nd = "n/m (EBITDA <= 0)" if math.isinf(feat.net_debt_to_ebitda) else f"{feat.net_debt_to_ebitda:.1f}x"
            out.append(Modifier("net_debt", -step, f"net debt {nd} EBITDA"))
    yrs = int(m.get("stability_years", 10))
    if feat.loss_years:
        if m.get("loss_year_penalty", True):
            out.append(Modifier("stability", -step, f"{feat.loss_years} loss year(s) in last {yrs}"))
    elif (feat.loss_years == 0 and feat.years_of_history >= yrs and feat.eps_yoy_stdev is not None
          and feat.eps_yoy_stdev <= m.get("eps_yoy_stdev_max", 0.30)):
        out.append(Modifier("stability", +step,
                            f"no loss in {yrs} years, EPS volatility {feat.eps_yoy_stdev:.2f}"))
    if structural_headwind and m.get("structural_headwind", True):
        out.append(Modifier("structural_headwind", -step, "structural headwind (set by owner)"))
    return out


def _eps_for(basis: str, feat: Features, notes: list[str]) -> Optional[float]:
    if basis == "ttm":
        return feat.eps_ttm
    if basis == "avg_3y":
        return feat.eps_3y_avg
    if basis == "avg_7y":
        if feat.eps_7y_avg is not None and feat.eps_7y_years < 7:
            notes.append(f"7yr average uses only {feat.eps_7y_years} years")
        return feat.eps_7y_avg
    return None


def classify_features(feat: Features, rules: Optional[dict] = None, *,
                      archetype: Optional[str] = None, structural_headwind: bool = False,
                      override_multiple: Optional[float] = None,
                      override_reason: str = "") -> Classification:
    """Apply the rules. ``archetype`` (from a confirmed entry) replaces the suggestion."""
    rules = rules or load_rules()
    arch_rules = rules.get("archetypes") or {}
    suggested = archetype is None
    if suggested:
        arch, conf, reasons = suggest_archetype(feat, rules)
    else:
        if archetype not in arch_rules:
            raise ValueError(f"{feat.ticker}: unknown archetype '{archetype}'")
        arch, conf, reasons = archetype, 1.0, ["archetype set by owner"]

    spec = arch_rules.get(arch) or {}
    base = spec.get("base_multiple")
    basis = spec.get("eps_basis") or "none"
    notes: list[str] = []
    cls = Classification(
        ticker=feat.ticker, archetype=arch, suggested=suggested, confidence=conf, reasons=reasons,
        base_multiple=base, modifiers=[], raw_multiple=None, buy_multiple=None, guardrails=[],
        median_pe_10y=feat.median_pe_10y, eps_basis=basis, eps_value=None, implied_buy_price=None,
        alt_metric=spec.get("alt_metric"), features=feat, error=feat.error,
    )
    if spec.get("alt_metric") == "dividend_yield":
        cls.alt_metric_value = feat.dividend_yield
    elif spec.get("alt_metric") == "price_to_sales":
        cls.alt_metric_value = feat.price_to_sales

    ov = _num(override_multiple)
    if ov is not None:
        cls.buy_multiple = ov
        cls.override_reason = override_reason
        cls.guardrails.append(f"override {ov:g}x wins: {override_reason or 'no reason given'}")
    elif base is not None:
        cls.modifiers = _modifiers(arch, feat, rules, structural_headwind)
        raw = float(base) + sum(m.delta for m in cls.modifiers)
        cls.raw_multiple = raw
        gr = rules.get("guardrails") or {}
        floor, ceil = float(gr.get("floor", 6)), float(gr.get("ceiling", 35))
        final = raw
        median = feat.median_pe_10y
        if gr.get("cap_at_own_median_pe", True):
            if median is not None and median > 0:
                if final > median:
                    cls.guardrails.append(f"capped at own {gr.get('median_years', 10)}-year median P/E {median:.1f}x")
                    final = median
            else:
                cls.guardrails.append("median P/E unavailable: cap not applied")
                cls.confidence = max(round(cls.confidence - 0.10, 2), 0.1)
        if final > ceil:
            cls.guardrails.append(f"ceiling {ceil:g}x")
            final = ceil
        if final < floor:
            cls.guardrails.append(f"floor {floor:g}x")
            final = floor
        cls.buy_multiple = round(final, 1)

    if cls.buy_multiple is not None:
        eps = _eps_for(basis, feat, notes)
        cls.eps_value = eps
        if eps is not None and eps > 0:
            cls.implied_buy_price = round(cls.buy_multiple * eps, 2)
        else:
            notes.append(f"{eps_basis_label(rules, basis)} unavailable or not positive: no implied price")
    cls.reasons = reasons + notes + list(feat.notes)
    return cls


def classify_ticker(ticker: str, rules: Optional[dict] = None, *, entry: Optional[dict] = None,
                    today: Optional[dt.date] = None, fund: Optional[dict] = None) -> Classification:
    """Fetch EODHD data and classify. A confirmed ``entry`` supplies archetype/override/headwind."""
    rules = rules or load_rules()
    feat = features_from_eodhd(ticker, today=today, rules=rules, fund=fund)
    return classify_with_entry(feat, rules, entry)


def sell_multiple_for(cls: Classification, rules: Optional[dict] = None) -> tuple[float, str]:
    """SELL multiple for a value wedge with no hand-set SELL: the stock's own
    10-year median P/E, held between ``sell.over_buy_min`` and
    ``sell.over_buy_max`` times the BUY multiple (valuation_archetypes.yaml).
    Returns (multiple, plain-English reason)."""
    rule = (rules or load_rules()).get("sell") or {}
    lo, hi = float(rule.get("over_buy_min", 1.5)), float(rule.get("over_buy_max", 3.0))
    bm = float(cls.buy_multiple)
    med = cls.median_pe_10y if rule.get("use_own_median_pe", True) else None
    if med and med > 0:
        sm = min(max(med, bm * lo), bm * hi)
        why = (f"own 10-year median P/E {med:.1f}x" if sm == med
               else f"{sm / bm:g}x BUY (own median {med:.1f}x is outside {lo:g}-{hi:g}x BUY)")
    else:
        sm, why = bm * lo, f"{lo:g}x BUY (no 10-year median P/E)"
    return round(sm, 1), why


def classification_for(ticker: str, today: Optional[dt.date] = None) -> Classification:
    """Classify with this ticker's entry in config/ticker_archetypes.yaml (the
    owner's confirmed archetype / override wins). For valuation YAMLs that say
    ``buy_multiple: archetype``."""
    from shared.archetype_sync import load_entries
    return classify_ticker(ticker, entry=load_entries().get(ticker), today=today)


def classify_with_entry(feat: Features, rules: dict, entry: Optional[dict]) -> Classification:
    entry = entry or {}
    confirmed = entry.get("status") == "confirmed" and entry.get("archetype") in (rules.get("archetypes") or {})
    return classify_features(
        feat, rules,
        archetype=entry["archetype"] if confirmed else None,
        structural_headwind=bool(entry.get("structural_headwind")),
        override_multiple=entry.get("override_multiple"),
        override_reason=entry.get("override_reason") or "",
    )
