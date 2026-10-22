# mike/rubric.py
#
# The six criteria of Mikebrisy's Stock Quality Assessment Framework v3.1
# ("True 0-5 Demonstrated Track Record Rubric"), base scores only.
#
# Each criterion function:
#   1. completes every calculation the framework prescribes for it, or records
#      formally why one is inapplicable (rule 8.1: no silent substitutes);
#   2. maps the result to the framework's base-score table (section 4);
#   3. records data-evidenced overlays the framework permits (section 4,
#      "Permitted overlay"), each with its reason;
#   4. records its hard-gate checks (section 8.3).
#
# Market Position (4.3) is the exception: its five tests need an evidence
# register, which mike/evidence.py builds. Here it only prepares the
# quantitative cross-checks the register is read against.
#
# Statutory figures first (rule 2): EODHD has no underlying figures. Exceptional
# items are normalised only from config/mike_overrides.yaml, where each one
# carries a source, so the reconciliation to statutory is always shown.

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Optional

from mike.series import YearRow

WINDOW = 5                     # framework default evidence period, years


# ---------------------------------------------------------------------------
# result types
# ---------------------------------------------------------------------------

@dataclass
class Calc:
    name: str
    formula: str
    value: Optional[float]
    display: str
    meaningful: bool = True
    note: str = ""


@dataclass
class Overlay:
    criterion: str
    adjustment: float            # -0.5 / +0.5
    reason: str
    evidence: str
    source: str = "EODHD statutory data"
    origin: str = "data"         # data | evidence-review | manual
    accepted: bool = True
    rejected_because: str = ""


@dataclass
class Gate:
    check: str
    passed: bool
    note: str = ""


@dataclass
class Criterion:
    key: str
    name: str
    period: str                  # evidence period label (section 10)
    window: str = ""             # actual FYs used
    calcs: list[Calc] = field(default_factory=list)
    base: Optional[float] = None
    base_reason: str = ""
    overlays: list[Overlay] = field(default_factory=list)
    final: Optional[float] = None
    rationale: str = ""
    flags: list[str] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)
    inapplicable: list[str] = field(default_factory=list)
    challenge: str = ""          # +/-0.5 adversarial note (8.4)
    metrics: dict = field(default_factory=dict)

    def calc(self, name: str) -> Optional[Calc]:
        return next((c for c in self.calcs if c.name == name), None)

    def as_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def pct(x: Optional[float], dp: int = 0) -> str:
    return "n/a" if x is None else f"{x * 100:.{dp}f}%"


def mult(x: Optional[float], dp: int = 1) -> str:
    return "n/a" if x is None else f"{x:.{dp}f}x"


def money(x: Optional[float], ccy: str = "") -> str:
    if x is None:
        return "n/a"
    a = abs(x)
    s = f"{x / 1e9:,.2f}bn" if a >= 1e9 else f"{x / 1e6:,.1f}m"
    return f"{ccy} {s}".strip()


def span(rows: list[YearRow]) -> str:
    return f"{rows[0].fy}-{rows[-1].fy}" if rows else "n/a"


def cagr(first: Optional[float], last: Optional[float], years: int) -> Optional[float]:
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def last_n(rows: list[YearRow], n: int) -> list[YearRow]:
    return rows[-n:] if len(rows) >= n else rows[:]


def changes(rows: list[YearRow], get) -> list[tuple[str, Optional[float]]]:
    """Year-on-year % change of get(row); None where the prior year is <= 0."""
    out = []
    for a, b in zip(rows, rows[1:]):
        va, vb = get(a), get(b)
        if va is None or vb is None or va <= 0:
            out.append((b.fy, None))
        else:
            out.append((b.fy, vb / va - 1))
    return out


# ---------------------------------------------------------------------------
# 4.1 Earnings Stability
# ---------------------------------------------------------------------------

STABILITY_TABLE = [
    (0.10, 5.0, "No annual decline greater than 10%"),
    (0.20, 4.0, "Maximum decline 10-20%"),
    (0.35, 3.0, "Maximum decline 20-35%"),
    (0.60, 2.0, "Maximum decline 35-60%"),
]


def earnings_stability(rows: list[YearRow], *, cyclical: bool = False) -> Criterion:
    c = Criterion("stability", "Earnings Stability", "5-10 years")
    win = last_n(rows, WINDOW + 1)
    c.window = span(win)
    eps_ch = changes(win, lambda r: r.eps)
    pbt_ch = changes(win, lambda r: r.pbt)
    losses = [r.fy for r in win[1:] if r.npat is not None and r.npat < 0]
    profitable = [r for r in win if r.npat is not None and r.npat > 0]
    rev_down = [fy for fy, g in changes(win, lambda r: r.revenue) if g is not None and g < -0.005]
    margins = [r.ebit_margin for r in win if r.ebit_margin is not None]
    m_sd = statistics.pstdev([max(-1, min(1, m)) for m in margins]) if len(margins) >= 3 else None

    def max_decline(ch):
        decl = []
        for fy, g in ch:
            if g is not None and g < 0:
                decl.append((-g, fy))
        return max(decl) if decl else (0.0, None)

    eps_decl, eps_fy = max_decline(eps_ch)
    pbt_decl, pbt_fy = max_decline(pbt_ch)
    # A year that swings from profit to loss is a >100% decline.
    for a, b in zip(win, win[1:]):
        if a.eps and a.eps > 0 and b.eps is not None and b.eps <= 0:
            eps_decl, eps_fy = max((eps_decl, eps_fy), (1.0 + abs(b.eps) / a.eps, b.fy))

    c.calcs = [
        Calc("Max annual EPS decline", "max over trailing 5 years of -(EPS_t / EPS_t-1 - 1); EPS = statutory NPAT / shares on issue",
             eps_decl, f"{pct(eps_decl)}" + (f" ({eps_fy})" if eps_fy else ""),
             note="Statutory EPS; EODHD carries no underlying EPS"),
        Calc("Max annual PBT decline (cross-check)", "max over trailing 5 years of -(PBT_t / PBT_t-1 - 1)",
             pbt_decl, f"{pct(pbt_decl)}" + (f" ({pbt_fy})" if pbt_fy else "")),
        Calc("Loss-making years", "count of years with statutory NPAT < 0", len(losses),
             f"{len(losses)}" + (f" ({', '.join(losses)})" if losses else "")),
        Calc("Revenue down-years", "count of years with revenue below the prior year", len(rev_down),
             f"{len(rev_down)} of {max(0, len(win) - 1)}"),
        Calc("EBIT margin variability", "population std dev of annual EBIT margin", m_sd, pct(m_sd, 1)),
    ]
    c.metrics = {"max_eps_decline": eps_decl, "max_pbt_decline": pbt_decl, "loss_years": len(losses),
                 "revenue_down_years": len(rev_down), "ebit_margin_sd": m_sd}

    if len(win) < 4:
        c.inapplicable.append("Fewer than three year-on-year EPS changes on EODHD: decline test cannot be completed")
        c.base = None
        c.base_reason = "Insufficient history"
        c.gates.append(Gate("Required decline calculation completed", False, "insufficient history"))
        return c

    if len(losses) >= 2 or len(profitable) < 3:
        c.base, c.base_reason = 0.0, "Repeated material losses or no established profit base"
    elif eps_decl > 0.60:
        c.base, c.base_reason = 1.0, "Maximum decline >60%, meaningful profitable base remains"
    else:
        for lim, score, label in STABILITY_TABLE:
            if eps_decl <= lim:
                c.base, c.base_reason = score, label
                break

    # Permitted -0.5: commodity exposure / unusually high margin or revenue volatility.
    if c.base and c.base > 0:
        if m_sd is not None and m_sd > 0.10:
            c.overlays.append(Overlay("stability", -0.5, "Unusually high margin volatility",
                                      f"EBIT margin std dev {pct(m_sd, 1)} over {c.window}"))
        elif cyclical:
            c.overlays.append(Overlay("stability", -0.5, "Commodity exposure",
                                      "Classified cyclical (config/ticker_archetypes.yaml)", "repo archetype"))
    c.gates += [
        Gate("Required decline calculation completed", True),
        Gate("Loss years and margin/revenue variability checked", True),
    ]
    c.rationale = (f"Max EPS fall {pct(eps_decl)}" + (f" in {eps_fy}" if eps_fy else "")
                   + f"; {len(losses)} loss year(s); revenue down {len(rev_down)} of {len(win) - 1} years")
    return c


# ---------------------------------------------------------------------------
# 4.2 Earnings Quality
# ---------------------------------------------------------------------------

def earnings_quality(rows: list[YearRow], ccy: str = "") -> Criterion:
    c = Criterion("quality", "Earnings Quality", "5-year cumulative")
    win = last_n(rows, WINDOW)
    c.window = span(win)
    complete = [r for r in win if None not in (r.cfo, r.ebitda, r.npat)]
    s_cfo = sum(r.cfo for r in complete)
    s_ebitda = sum(r.ebitda for r in complete)
    s_npat = sum(r.npat for r in complete)
    s_fcf = sum(r.fcf for r in complete if r.fcf is not None)
    s_rev = sum(r.revenue or 0.0 for r in complete)
    s_sbc = sum(r.sbc or 0.0 for r in complete)
    s_opnpat = sum((r.nopat or 0.0) for r in complete)

    ebitda_ok = s_ebitda > 0 and s_ebitda > 0.02 * s_rev
    npat_ok = s_npat > 0 and s_npat > 0.02 * s_rev
    cfo_ebitda = s_cfo / s_ebitda if ebitda_ok else None
    fcf_npat = s_fcf / s_npat if npat_ok else None

    c.calcs = [
        Calc("5y cumulative CFO", "sum of operating cash flow", s_cfo, money(s_cfo, ccy)),
        Calc("5y cumulative EBITDA", "sum of EBITDA", s_ebitda, money(s_ebitda, ccy)),
        Calc("5y cumulative NPAT", "sum of statutory NPAT", s_npat, money(s_npat, ccy)),
        Calc("5y cumulative FCF", "sum of (CFO - capital expenditure); leases not deducted", s_fcf, money(s_fcf, ccy)),
        Calc("CFO / EBITDA (5y cumulative)", "sum CFO / sum EBITDA", cfo_ebitda, pct(cfo_ebitda),
             meaningful=cfo_ebitda is not None,
             note="" if ebitda_ok else "Cumulative EBITDA negative or near zero: ratio not meaningful"),
        Calc("FCF / NPAT (5y cumulative)", "sum FCF / sum NPAT", fcf_npat, pct(fcf_npat),
             meaningful=fcf_npat is not None,
             note="" if npat_ok else "Cumulative NPAT negative or near zero: ratio not meaningful"),
        Calc("Share-based payments (5y)", "sum of stockBasedCompensation (review item)", s_sbc, money(s_sbc, ccy)),
    ]
    c.metrics = {"cfo_ebitda": cfo_ebitda, "fcf_npat": fcf_npat, "sum_cfo": s_cfo, "sum_fcf": s_fcf,
                 "sum_npat": s_npat, "years": len(complete)}
    c.inapplicable.append("Capitalised development/software: not separately reported by EODHD; review in the annual report")
    c.inapplicable.append("Maintenance vs growth capex split: not reported by EODHD; all capex deducted")

    if len(complete) < 3:
        c.inapplicable.append("Fewer than three complete years of CFO, EBITDA and NPAT")
        c.base_reason = "Insufficient history"
        c.gates.append(Gate("Both prescribed five-year ratios completed or ruled inapplicable", False, "insufficient history"))
        return c

    neg_fcf_years = sum(1 for r in complete if r.fcf is not None and r.fcf < 0)
    if (s_cfo <= 0 or s_fcf <= 0) and (not npat_ok or neg_fcf_years >= 3):
        c.base, c.base_reason = 0.0, "Persistently negative cumulative CFO/FCF or no meaningful positive earnings base"
    elif fcf_npat is None:
        # Denominator problem: assess the cash economics directly, never a flattering ratio.
        c.base = 1.0 if s_fcf > 0 else 0.0
        c.base_reason = "NPAT denominator not meaningful; scored on direct cash economics"
        c.flags.append("Denominator distortion: cumulative NPAT negative or near zero, ratio withheld")
    else:
        strong = cfo_ebitda is not None and cfo_ebitda >= 0.80
        good = cfo_ebitda is not None and cfo_ebitda >= 0.70
        if fcf_npat >= 0.95 and strong:
            c.base, c.base_reason = 5.0, "FCF/NPAT ~>=100% and strong CFO/EBITDA"
        elif fcf_npat >= 0.80 and good:
            c.base, c.base_reason = 4.0, "FCF/NPAT >=80%; strong conversion"
        elif fcf_npat >= 0.80 or fcf_npat >= 0.70:
            c.base, c.base_reason = 3.0, ("FCF/NPAT >=80% but CFO/EBITDA below 70%" if fcf_npat >= 0.80
                                           else "FCF/NPAT 70-80%; good conversion")
        elif fcf_npat >= 0.50:
            c.base, c.base_reason = 2.0, "FCF/NPAT 50-70%; mixed conversion"
        else:
            c.base, c.base_reason = 1.0, "FCF/NPAT <50%; weak conversion"

    # Statutory-vs-operating gaps: a year where statutory NPAT departs from
    # operating profit after tax by more than 30% either way.
    gaps = [r.fy for r in complete if r.nopat and r.nopat > 0 and r.npat is not None
            and abs(r.npat - r.nopat) > 0.30 * r.nopat]
    if gaps:
        c.flags.append(f"Statutory NPAT departs >30% from operating profit after tax in {', '.join(gaps)}")
        if npat_ok and s_opnpat > 0 and s_npat < 0.7 * s_opnpat:
            c.flags.append("Statutory NPAT well below operating profit: FCF/NPAT flattered by non-cash charges")
    if len(gaps) >= 2 and c.base and c.base > 0:
        c.overlays.append(Overlay("quality", -0.5, "Persistent statutory-versus-underlying gaps",
                                  f"Statutory NPAT departs >30% from operating profit in {', '.join(gaps)}"))
    c.gates += [
        Gate("Both prescribed five-year ratios completed or ruled inapplicable", True),
        Gate("FCF definition reconciled", True, "FCF = CFO - capitalExpenditures (EODHD); leases not deducted"),
        Gate("Denominator distortion tested", True, "NPAT and EBITDA tested for negative/near-zero"),
    ]
    c.rationale = f"FCF/NPAT {pct(fcf_npat)}, CFO/EBITDA {pct(cfo_ebitda)} over {c.window}"
    return c


# ---------------------------------------------------------------------------
# 4.3 Demonstrated Market Position (evidence register filled by evidence.py)
# ---------------------------------------------------------------------------

MARKET_TESTS = [
    ("leadership", "Market leadership", "Reliable evidence of top-3 share, clear niche leadership, or sustained share gains."),
    ("retention", "Retention / switching costs", "Quantitative retention, renewal, repeat-business evidence, or demonstrably costly switching."),
    ("pricing", "Pricing power", "Historical ability to raise price at/above inflation without material volume/share loss or margin damage."),
    ("barriers", "Structural barriers", "Regulation, IP, network/data effects, scale, distribution, embedded workflows or other barriers demonstrably affecting competition."),
    ("trajectory", "Competitive trajectory", "Stable/rising share, win rates, customer economics or relative competitive performance over at least ~3 years."),
]


def market_position_shell(rows: list[YearRow]) -> Criterion:
    c = Criterion("market", "Demonstrated Market Position", "3-5 years")
    win = last_n(rows, WINDOW + 1)
    c.window = span(win)
    margins = [(r.fy, r.ebit_margin) for r in win if r.ebit_margin is not None]
    c.calcs = [Calc("EBIT margin by year (context for pricing tests)", "EBIT / revenue",
                    None, ", ".join(f"{fy} {pct(m, 1)}" for fy, m in margins) or "n/a")]
    c.base_reason = "Evidence register not completed"
    return c


# ---------------------------------------------------------------------------
# 4.4 Balance-Sheet Strength
# ---------------------------------------------------------------------------

def _lev_band(lev: float) -> tuple[float, str]:
    if lev <= 1.0:
        return 4.0, "Net debt/EBITDA 0-1x"
    if lev <= 2.0:
        return 3.0, "Net debt/EBITDA 1-2x"
    if lev <= 3.5:
        return 2.0, "Net debt/EBITDA 2-3.5x"
    return 1.0, "Net debt/EBITDA >3.5x"


def _cover_band(cover: float) -> tuple[float, str]:
    if cover > 10:
        return 4.0, "interest cover >10x"
    if cover >= 5:
        return 3.0, "interest cover 5-10x"
    if cover >= 2.5:
        return 2.0, "interest cover 2.5-5x"
    return 1.0, "interest cover <2.5x"


def balance_sheet(rows: list[YearRow], interim: list[dict], ccy: str = "") -> Criterion:
    c = Criterion("balance", "Balance-Sheet Strength", "Current + trend")
    win = last_n(rows, 4)
    c.window = span(win)
    last = rows[-1]
    lev = None
    if last.net_debt is not None and last.ebitda and last.ebitda > 0:
        lev = last.net_debt / last.ebitda
    cover = last.ebit / last.interest if (last.ebit is not None and last.interest and last.interest > 0) else None
    back = win[0]
    lev_back = back.net_debt / back.ebitda if (back.net_debt is not None and back.ebitda and back.ebitda > 0) else None

    # Loss-making in the framework's sense: the business itself burns cash or
    # has no operating profit. A statutory loss from a non-cash impairment, with
    # positive operating cash flow, is not cash burn.
    burning = ((last.ebitda is not None and last.ebitda <= 0)
               or (last.npat is not None and last.npat < 0 and ((last.cfo or 0) < 0 or (last.fcf or 0) < 0)))
    raised = [r.fy for r in last_n(rows, 3) if r.equity_issued and r.cash and r.equity_issued > 0.10 * max(r.cash, 1)]
    recent_burn = None
    if interim:
        recent = [p["fcf"] for p in interim[-2:] if p.get("fcf") is not None]
        if recent:
            recent_burn = -min(0.0, sum(recent)) * (4 / len(recent)) if len(interim) >= 4 else -min(0.0, sum(recent)) * 2
    annual_burn = -last.fcf if (last.fcf is not None and last.fcf < 0) else 0.0
    burn = max(annual_burn, recent_burn or 0.0)
    runway = (last.cash / burn) if (burn > 0 and last.cash is not None) else None

    c.calcs = [
        Calc("Cash and short-term investments", "balance sheet", last.cash, money(last.cash, ccy)),
        Calc("Gross debt (incl. lease liabilities)", "shortLongTermDebtTotal", last.debt, money(last.debt, ccy)),
        Calc("Net debt", "gross debt - cash", last.net_debt, money(last.net_debt, ccy)),
        Calc("EBITDA", "latest FY", last.ebitda, money(last.ebitda, ccy)),
        Calc("Net debt / EBITDA", "latest FY", lev, "net cash" if (last.net_debt is not None and last.net_debt <= 0) else mult(lev),
             meaningful=not (last.ebitda is not None and last.ebitda <= 0)),
        Calc("Interest cover", "EBIT / interest expense", cover, mult(cover), meaningful=cover is not None,
             note="" if cover is not None else "No interest expense reported or EBIT unavailable"),
        Calc("Net debt / EBITDA three years earlier", back.fy, lev_back, mult(lev_back)),
        Calc("Annual cash burn (FCF, latest FY)", "-(CFO - capex) when negative", annual_burn, money(annual_burn, ccy)),
        Calc("Recent interim cash burn (annualised)", "latest two interim periods, annualised", recent_burn,
             money(recent_burn, ccy), meaningful=recent_burn is not None,
             note="" if interim else "No interim cash-flow periods on EODHD"),
        Calc("Cash runway", "cash / annual burn", runway, "n/a (self-funding)" if runway is None else f"{runway:.1f} years"),
        Calc("External equity raised (last 3 FYs)", "issuanceOfCapitalStock > 10% of cash", len(raised),
             ", ".join(raised) or "none"),
    ]
    c.metrics = {"nd_ebitda": lev, "interest_cover": cover, "nd_ebitda_3y": lev_back, "runway_years": runway,
                 "burning": burning, "equity_raised_years": raised}
    c.inapplicable.append("Covenant headroom and debt maturity profile: not on EODHD; review in the annual report")

    if last.net_debt is None:
        c.base_reason = "No cash/debt on EODHD for the latest year"
        c.gates.append(Gate("Leverage and interest cover checked", False, "no balance-sheet data"))
        return c

    if burning or (last.ebitda is not None and last.ebitda <= 0):
        # Loss-making / cash-burning: net cash alone cannot justify a high score.
        if runway is None or runway >= 4:
            s, why = 3.0, "Loss-making: net cash with long runway, still externally exposed"
        elif runway >= 2:
            s, why = 2.0, "Loss-making: 2-4 years of cash runway"
        elif runway >= 1:
            s, why = 1.0, "Loss-making: thin runway, external-funding dependence"
        else:
            s, why = 0.0, "Cash runway under a year with no internally funded path"
        if len(raised) >= 2 and s > 1:
            s, why = 1.0, "Loss-making with repeated external equity funding"
        if last.net_debt > 0 and s > 1:
            s, why = 1.0, "Net debt with negative earnings"
        c.base, c.base_reason = s, why
    elif last.net_debt <= 0 and (last.cfo or 0) > 0:
        c.base, c.base_reason = 5.0, "Net cash; internally funded operations"
        if len(raised) >= 2:
            c.base, c.base_reason = 3.0, ("Net cash, but equity raised in " + ", ".join(raised)
                                          + ": recent raises are not self-funding strength")
    else:
        s1, why1 = _lev_band(lev if lev is not None else 99)
        if len(raised) >= 2 and s1 > 3:
            s1, why1 = 3.0, why1 + ", but repeated equity raises"
        s, why = s1, why1
        if cover is not None:
            s2, why2 = _cover_band(cover)
            if s2 < s1:
                s, why = s2, f"{why1}, but {why2} (lower signal used)"
            else:
                why = f"{why1}; {why2}"
        c.base, c.base_reason = s, why

    c.gates += [
        Gate("Leverage and interest cover checked where meaningful", True),
        Gate("Cash runway and external-funding dependence assessed for loss-makers", True,
             "assessed" if burning else "not loss-making"),
        Gate("Recent equity raise not mistaken for self-funding strength", True,
             f"raises in {', '.join(raised)}" if raised else "no material raises"),
    ]
    if burning:
        c.rationale = f"Loss-making; runway {'n/a' if runway is None else f'{runway:.1f}y'}; net {'cash' if last.net_debt <= 0 else 'debt'} {money(abs(last.net_debt), ccy)}"
    elif last.net_debt <= 0:
        c.rationale = f"Net cash {money(-last.net_debt, ccy)} at {last.fy}"
    else:
        c.rationale = f"Net debt/EBITDA {mult(lev)}, interest cover {mult(cover)} at {last.fy}"
    return c


# ---------------------------------------------------------------------------
# 4.5 Returns on Capital
# ---------------------------------------------------------------------------

def returns_on_capital(rows: list[YearRow], wacc: float) -> Criterion:
    c = Criterion("returns", "Returns on Capital", "5 years")
    win = last_n(rows, WINDOW + 1)
    c.window = span(win[1:]) if len(win) > 1 else span(win)
    roic, roe, roce, distorted = [], [], [], []
    for a, b in zip(win, win[1:]):
        if b.nopat is not None and a.invested_capital is not None and b.invested_capital is not None:
            ic = (a.invested_capital + b.invested_capital) / 2
            if ic <= 0:
                distorted.append(b.fy)
            else:
                r = b.nopat / ic
                roic.append((b.fy, r))
                if r > 1.0:
                    distorted.append(b.fy)
        if b.npat is not None and a.equity and b.equity and (a.equity + b.equity) > 0:
            roe.append((b.fy, b.npat / ((a.equity + b.equity) / 2)))
        if b.nopat is not None and a.capital_employed and b.capital_employed and (a.capital_employed + b.capital_employed) > 0:
            roce.append((b.fy, b.nopat / ((a.capital_employed + b.capital_employed) / 2)))

    vals = [r for _, r in roic]
    avg = statistics.mean(vals) if vals else None
    med = statistics.median(vals) if vals else None
    first, last = win[0], win[-1]
    inc = None
    if (first.nopat is not None and last.nopat is not None and first.invested_capital is not None
            and last.invested_capital is not None):
        d_ic = last.invested_capital - first.invested_capital
        if d_ic > 0:
            inc = (last.nopat - first.nopat) / d_ic
    roe_avg = statistics.mean([r for _, r in roe]) if roe else None
    roce_avg = statistics.mean([r for _, r in roce]) if roce else None

    meaningful = bool(vals) and not distorted
    c.calcs = [
        Calc("ROIC by year", "NOPAT / average invested capital; NOPAT = EBIT x (1 - effective tax, 0-35%); "
             "invested capital = equity + debt (incl. leases) - cash", None,
             ", ".join(f"{fy} {pct(r)}" for fy, r in roic) or "n/a"),
        Calc("Five-year average ROIC", "mean of annual ROIC", avg, pct(avg, 1), meaningful=meaningful),
        Calc("Five-year median ROIC", "median of annual ROIC", med, pct(med, 1), meaningful=meaningful),
        Calc("WACC", "config/mike.yaml (default) or per-ticker override", wacc, pct(wacc, 1)),
        Calc("Incremental ROIC", "change in NOPAT / capital added over the window", inc, pct(inc),
             meaningful=inc is not None, note="" if inc is not None else "Invested capital did not rise: not meaningful"),
        Calc("ROE (cross-check)", "NPAT / average equity, mean", roe_avg, pct(roe_avg, 1)),
        Calc("ROCE after tax (cross-check)", "NOPAT / average (total assets - current liabilities), mean", roce_avg, pct(roce_avg, 1)),
    ]
    c.metrics = {"avg_roic": avg, "median_roic": med, "incremental_roic": inc, "roe": roe_avg, "roce": roce_avg,
                 "wacc": wacc, "distorted_years": distorted}

    basis, measure = "ROIC", (min(avg, med) if vals else None)
    if not meaningful:
        if distorted:
            c.flags.append(f"Invested capital near zero/negative or ROIC >100% in {', '.join(distorted)}: "
                           "ROIC not economically meaningful; triangulated with ROCE after tax")
        basis, measure = "ROCE after tax", roce_avg
    if measure is None:
        c.base_reason = "Returns could not be calculated from EODHD data"
        c.gates.append(Gate("Five-year average/median ROIC and WACC comparison completed", False, "no data"))
        return c

    neg_years = sum(1 for _, r in roic if r < 0)
    if measure <= 0 or neg_years >= 3:
        s, why = 0.0, "Persistently negative NOPAT/ROIC"
    elif measure > min(0.20, 2.5 * wacc):
        s, why = 5.0, f"{basis} >20% / >2.5x WACC, sustained"
        if inc is not None and inc < 1.25 * wacc:
            s, why = 4.0, f"{basis} >20% but incremental returns only {pct(inc)}: not 'strong incremental returns'"
    elif measure > min(0.15, 1.75 * wacc):
        s, why = 4.0, f"{basis} ~15-20% / >1.75x WACC"
    elif measure > min(0.10, 1.25 * wacc):
        s, why = 3.0, f"{basis} ~10-15% / >1.25x WACC"
    elif measure >= 0.9 * wacc:
        s, why = 2.0, f"{basis} around WACC"
    else:
        s, why = 1.0, f"{basis} below WACC but positive"
    c.base, c.base_reason = s, why + f" (lower of average and median used: {pct(measure, 1)})"
    c.gates += [
        Gate("Five-year average/median ROIC and WACC comparison completed", True,
             "" if meaningful else "ROIC not meaningful; ROCE substituted and disclosed"),
        Gate("Denominator distortion checked", True),
        Gate("Negative NOPAT/ROIC tested against the zero-score rule", True, f"{neg_years} negative year(s)"),
    ]
    c.rationale = f"{basis} avg {pct(avg if meaningful else roce_avg)}, median {pct(med) if meaningful else 'n/m'}, incremental {pct(inc)} vs WACC {pct(wacc)}"
    return c


# ---------------------------------------------------------------------------
# 4.6 Growth Track Record
# ---------------------------------------------------------------------------

def growth_track_record(rows: list[YearRow], ccy: str = "", min_revenue: float = 5e6) -> Criterion:
    c = Criterion("growth", "Growth Track Record", "5-10 years")
    win = last_n(rows, WINDOW + 1)
    c.window = span(win)
    n = len(win) - 1
    long = last_n(rows, 11)
    rev_cagr = cagr(win[0].revenue, win[-1].revenue, n) if n > 0 else None
    rev10 = cagr(long[0].revenue, long[-1].revenue, len(long) - 1) if len(long) > 6 else None
    eps_cagr = cagr(win[0].eps, win[-1].eps, n) if n > 0 else None
    ebit_cagr = cagr(win[0].ebit, win[-1].ebit, n) if n > 0 else None
    earn_cagr, earn_basis = (eps_cagr, "EPS") if eps_cagr is not None else (ebit_cagr, "EBIT")
    up = [fy for fy, g in changes(win, lambda r: r.revenue) if g is not None and g > 0]
    latest_rev = win[-1].revenue or 0.0
    meaningful_years = [r for r in rows if r.revenue and r.revenue >= max(min_revenue, 0.10 * latest_rev)]
    sh_cagr = cagr(win[0].shares, win[-1].shares, n) if n > 0 else None
    d_int = (win[-1].intangibles or 0.0) - (win[0].intangibles or 0.0)
    d_rev = latest_rev - (win[0].revenue or 0.0)
    acq_heavy = (d_int > 0 and win[-1].total_assets and d_int > 0.10 * win[-1].total_assets
                 and d_rev > 0 and d_int >= 0.5 * d_rev)

    c.calcs = [
        Calc("Revenue CAGR (5y)", "(rev_end / rev_start)^(1/5) - 1", rev_cagr, pct(rev_cagr, 1)),
        Calc("Revenue CAGR (10y context)", "where EODHD has the history", rev10, pct(rev10, 1), meaningful=rev10 is not None),
        Calc(f"{earn_basis} CAGR (5y)", "statutory; EBIT used where EPS endpoints are not positive", earn_cagr, pct(earn_cagr, 1),
             meaningful=earn_cagr is not None),
        Calc("Years of positive revenue growth", "count", len(up), f"{len(up)} of {n}"),
        Calc("Share count CAGR (dilution)", "shares on issue", sh_cagr, pct(sh_cagr, 1)),
        Calc("Acquisition contribution (proxy)", "increase in goodwill + intangibles vs increase in revenue",
             d_int, f"{money(d_int, ccy)} intangibles added vs {money(d_rev, ccy)} revenue added",
             note="EODHD has no organic/acquired split; intangibles growth used as the acquisition signal"),
        Calc("Years of meaningful commercial revenue", f"revenue >= max({money(min_revenue)}, 10% of latest)",
             len(meaningful_years), str(len(meaningful_years))),
    ]
    c.metrics = {"revenue_cagr": rev_cagr, "revenue_cagr_10y": rev10, "earnings_cagr": earn_cagr,
                 "earnings_basis": earn_basis, "up_years": len(up), "share_cagr": sh_cagr,
                 "acquisition_heavy": bool(acq_heavy), "meaningful_years": len(meaningful_years)}

    if rev_cagr is None or n < 3:
        if latest_rev < min_revenue:
            c.base, c.base_reason = 0.0, "No meaningful commercial revenue base"
        else:
            c.base_reason = "Revenue CAGR could not be calculated"
            c.inapplicable.append("Revenue missing or non-positive at an end of the window")
            c.gates.append(Gate("CAGR duration and consistency checked", False))
        return c

    g = rev_cagr if earn_cagr is None else min(rev_cagr, earn_cagr)
    consistent = len(up) >= n - 1
    if latest_rev < min_revenue:
        s, why = 0.0, "No meaningful commercial revenue base"
    elif g < 0:
        s, why = 1.0, "Negative CAGR / sustained contraction"
    elif g < 0.04:
        s, why = 2.0, "0-4% CAGR"
    elif g < 0.08:
        s, why = 3.0, "4-8% CAGR"
    elif g < 0.12:
        s, why = (4.0, "8-12% CAGR, generally consistent") if consistent else (3.0, "8-12% CAGR with variability")
    else:
        s, why = (5.0, ">12% CAGR, positive almost every year") if consistent else (4.0, ">12% CAGR but less consistent")
    why += f" (lower of revenue {pct(rev_cagr, 1)} and {earn_basis} {pct(earn_cagr, 1)})" if earn_cagr is not None else f" (revenue {pct(rev_cagr, 1)}; earnings CAGR not meaningful)"
    if acq_heavy and s > 2:
        s, why = min(s, 3.0), why + "; growth acquisition-assisted"
    # Short-history rule.
    if len(meaningful_years) < 3 and s > 2:
        s, why = 2.0, why + "; <3 years of meaningful commercial history (short-history rule)"
        c.flags.append("Short commercial history: quarterly/semi-annual drill-down required before publication")
    elif len(meaningful_years) < WINDOW + 1 and s > 3:
        s, why = 3.0, why + "; full five-year commercial record not yet established"
    c.base, c.base_reason = s, why

    if s > 0:
        if acq_heavy:
            c.overlays.append(Overlay("growth", -0.5, "Material acquisition dependence",
                                      f"Goodwill and intangibles up {money(d_int, ccy)} against revenue up {money(d_rev, ccy)}"))
        elif sh_cagr is not None and sh_cagr > 0.05:
            c.overlays.append(Overlay("growth", -0.5, "Dilution", f"Share count up {pct(sh_cagr, 1)} a year"))
    c.gates += [
        Gate("Organic growth separated from M&A", True, "proxy: intangibles growth (EODHD has no organic split)"),
        Gate("CAGR duration and consistency checked", True),
        Gate("Short-history rule applied", True, f"{len(meaningful_years)} meaningful years"),
    ]
    c.rationale = (f"Revenue CAGR {pct(rev_cagr, 1)}, {earn_basis} CAGR {pct(earn_cagr, 1)}; "
                   f"revenue up {len(up)} of {n} years")
    return c
