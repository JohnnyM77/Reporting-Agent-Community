"""Esther's valuation maths. The model proposes assumptions; this module decides the numbers.

Mirrors Simply Wall St's Narrative valuator. SWS takes ONE set of slider
inputs (revenue growth, profit margin, future P/E), so Esther produces one
Narrative case, and the three inputs JM types into SWS produce the same answer here:

    future revenue   = revenue today x (1 + growth) ^ years
    future earnings  = future revenue x net margin
    future value/sh  = future earnings x future P/E / future shares
    value today/sh   = future value/sh / (1 + discount rate) ^ years

then converted from the reporting currency into the currency the shares trade
in (Computershare, Brambles and BHP report in US$ but trade in A$).

No dividends are added back, same as SWS. That understates high-payout names
(NHC, BHP), so the dividend add-on is shown on its own line and is never folded
into the SWS-comparable number.

An optional stress case (JM's private downside check) is valued the same way.
It is never published and never averaged into the Narrative value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


class ValuationInputError(ValueError):
    """An assumption or base figure is missing or outside a sane range."""


@dataclass(frozen=True)
class BaseFigures:
    """What the valuation starts from. All money in *report_currency* millions."""

    revenue_m: float
    shares_m: float
    report_currency: str = "AUD"
    price_currency: str = "AUD"
    fx_report_to_price: float = 1.0  # 1 unit of report currency buys this much price currency
    years: int = 5
    discount_rate: float = 0.075
    share_change_pa: float = 0.0  # +0.01 = 1% dilution a year, -0.01 = 1% buyback a year
    dps: float = 0.0  # current annual ordinary dividend per share, report currency (display-only add-on)

    def validate(self) -> None:
        if not self.revenue_m or self.revenue_m <= 0:
            raise ValuationInputError("revenue_m must be positive")
        if not self.shares_m or self.shares_m <= 0:
            raise ValuationInputError("shares_m must be positive")
        if not self.fx_report_to_price or self.fx_report_to_price <= 0:
            raise ValuationInputError("fx_report_to_price must be positive")
        if not 1 <= self.years <= 10:
            raise ValuationInputError("years must be 1-10")
        if not 0 <= self.discount_rate <= 0.25:
            raise ValuationInputError("discount_rate must be 0-25%")
        if not -0.10 <= self.share_change_pa <= 0.10:
            raise ValuationInputError("share_change_pa must be within +/-10% a year")


@dataclass(frozen=True)
class Scenario:
    """One set of SWS slider inputs, as decimals: 0.05 is 5%."""

    name: str
    revenue_growth: float
    net_margin: float
    future_pe: float
    rationale: str = ""

    def validate(self) -> None:
        if not -0.30 <= self.revenue_growth <= 0.60:
            raise ValuationInputError(f"{self.name}: revenue growth {self.revenue_growth:.1%} is outside -30%..60%")
        if not -0.50 <= self.net_margin <= 0.80:
            raise ValuationInputError(f"{self.name}: net margin {self.net_margin:.1%} is outside -50%..80%")
        if not 0 < self.future_pe <= 100:
            raise ValuationInputError(f"{self.name}: future P/E {self.future_pe} is outside 0..100x")


@dataclass
class ScenarioValue:
    name: str
    revenue_growth: float
    net_margin: float
    future_pe: float
    rationale: str
    future_revenue_m: float
    future_earnings_m: float
    future_shares_m: float
    future_value_per_share: float  # price currency, in year N
    value_today: float  # price currency, discounted


@dataclass
class ValuationResult:
    narrative: ScenarioValue
    price: Optional[float]
    base: BaseFigures
    stress: Optional[ScenarioValue] = None  # private downside check, never published
    implied_growth_at_price: Optional[float] = None  # growth that justifies today's price on the case margin/PE
    dividends_pv: float = 0.0  # PV of today's dividend held flat for the horizon, price currency
    warnings: list[str] = field(default_factory=list)

    @property
    def value(self) -> float:
        return self.narrative.value_today

    @property
    def upside(self) -> Optional[float]:
        return (self.value / self.price - 1) if self.price else None

    @property
    def value_with_dividends(self) -> float:
        return self.value + self.dividends_pv

    @property
    def upside_with_dividends(self) -> Optional[float]:
        return (self.value_with_dividends / self.price - 1) if self.price else None

    def to_dict(self) -> dict:
        return {
            "narrative": asdict(self.narrative),
            "stress": asdict(self.stress) if self.stress else None,
            "value": self.value,
            "price": self.price,
            "upside": self.upside,
            "base": asdict(self.base),
            "implied_growth_at_price": self.implied_growth_at_price,
            "dividends_pv": self.dividends_pv,
            "warnings": list(self.warnings),
        }


def value_scenario(s: Scenario, b: BaseFigures) -> ScenarioValue:
    s.validate()
    fut_rev = b.revenue_m * (1 + s.revenue_growth) ** b.years
    fut_earn = fut_rev * s.net_margin
    fut_shares = b.shares_m * (1 + b.share_change_pa) ** b.years
    fut_value = fut_earn * s.future_pe / fut_shares * b.fx_report_to_price
    today = fut_value / (1 + b.discount_rate) ** b.years
    return ScenarioValue(
        name=s.name,
        revenue_growth=s.revenue_growth,
        net_margin=s.net_margin,
        future_pe=s.future_pe,
        rationale=s.rationale,
        future_revenue_m=fut_rev,
        future_earnings_m=fut_earn,
        future_shares_m=fut_shares,
        future_value_per_share=fut_value,
        value_today=today,
    )


def implied_growth(price: float, margin: float, pe: float, b: BaseFigures) -> Optional[float]:
    """Revenue growth a year that makes the model value equal *price*, holding margin and P/E.

    The reverse-DCF question: what is Mr Market already assuming? Solved in
    closed form. None when margin or P/E make it meaningless.
    """
    if price <= 0 or margin <= 0 or pe <= 0:
        return None
    fut_shares = b.shares_m * (1 + b.share_change_pa) ** b.years
    needed_future_rev = price * (1 + b.discount_rate) ** b.years * fut_shares / (b.fx_report_to_price * margin * pe)
    ratio = needed_future_rev / b.revenue_m
    if ratio <= 0:
        return None
    return ratio ** (1 / b.years) - 1


def dividends_pv(b: BaseFigures) -> float:
    """What SWS leaves out: today's dividend, held flat, collected for the horizon, discounted.

    Deliberately crude (no growth, no cut) and shown as a separate line, never
    folded into the SWS-comparable number.
    """
    if not b.dps or b.dps <= 0:
        return 0.0
    d = b.dps * b.fx_report_to_price
    return sum(d / (1 + b.discount_rate) ** t for t in range(1, b.years + 1))


def run_valuation(
    narrative: Scenario,
    base: BaseFigures,
    price: Optional[float] = None,
    stress: Optional[Scenario] = None,
) -> ValuationResult:
    """Value the Narrative case (and the private stress case, if given). Raises ValuationInputError on bad inputs."""
    base.validate()
    n = value_scenario(narrative, base)
    s = value_scenario(stress, base) if stress else None
    warnings = []
    if n.value_today <= 0:
        warnings.append("Narrative case value is zero or negative")
    if s and s.value_today > n.value_today:
        warnings.append("stress case is worth more than the Narrative case: check the inputs")
    return ValuationResult(
        narrative=n,
        price=price,
        base=base,
        stress=s,
        implied_growth_at_price=implied_growth(price, n.net_margin, n.future_pe, base) if price else None,
        dividends_pv=dividends_pv(base),
        warnings=warnings,
    )
