from __future__ import annotations

from dataclasses import dataclass


HARRY_TIER = "Harry: thesis broken"
ON_DEMAND_TIER = "On demand: no trigger"


@dataclass
class AlertClassification:
    triggered: bool
    tier: str
    reasons: list[str]
    harry_flag: bool = False


def apply_harry_flag(alert: AlertClassification, flag: dict | None) -> AlertClassification:
    """Harry read the thesis as BROKEN: force a sell analysis, near a high or not.

    Keeps Sally's own tier when her screens also fired, so her valuation read
    is not lost; otherwise the tier says why the name is here.
    """
    if flag is None:
        return alert
    raised = flag.get("raised") or "recently"
    reason = f"Harry Hindsight reads the thesis as BROKEN (flagged {raised}); sell analysis forced"
    tier = alert.tier if alert.triggered else HARRY_TIER
    return AlertClassification(triggered=True, tier=tier, reasons=list(alert.reasons) + [reason], harry_flag=True)


def sally_verdict(alert: AlertClassification) -> str:
    if alert.harry_flag:
        return "Sell review: Harry says thesis broken"
    if alert.tier == ON_DEMAND_TIER:
        return "No trigger: wedge check only"
    return (
        "Trim candidate"
        if alert.tier == "Tier 3: Deep Review"
        else "Hold but stop adding"
        if alert.tier == "Tier 2: Review"
        else "Watch only"
    )


def classify_alert(
    distance_to_high: float,
    threshold: float,
    pe_ratio_3y: float | None,
    pe_ratio_5y: float | None,
    pe_ratio_10y: float | None,
    valuation_percentile: float | None,
    evidence_strength: float,
    review_ratio: float = 1.15,
    deep_ratio: float = 1.35,
    wedge: dict | None = None,
) -> AlertClassification:
    """52-week high is a trigger to look; the value wedge says what is there.

    ``wedge`` (optional) carries ``position`` (0 = on BUY, 1 = on SELL),
    ``actual_pe``, ``sell_pe`` and ``sell_value``. Price above SELL is a
    valuation trigger on its own, with or without a price high.
    """
    reasons: list[str] = []
    near_high = distance_to_high <= threshold
    position = (wedge or {}).get("position")
    above_sell = position is not None and position > 1
    wedge_reason = ""
    if above_sell:
        pe = wedge.get("actual_pe")
        wedge_reason = (
            f"price above SELL value ${wedge.get('sell_value', 0):,.2f}: PE "
            + (f"{pe:.0f}x" if pe else "n/a")
            + f" vs SELL multiple {wedge.get('sell_pe', 0):g}x"
        )

    if not near_high:
        if above_sell:
            return AlertClassification(
                triggered=True, tier="Tier 2: Review",
                reasons=[wedge_reason + " (valuation trigger; not near the 52-week high)"],
            )
        return AlertClassification(triggered=False, tier="none", reasons=[])

    reasons.append(f"within {(threshold*100):.1f}% of 52-week high")
    stretch_signals = 0
    if above_sell:
        stretch_signals += 1
        reasons.append(wedge_reason)
    elif position is not None:
        reasons.append(f"price {position:.0%} of the way from BUY to SELL: inside the wedge")
    for name, ratio in (("PE vs 3y", pe_ratio_3y), ("PE vs 5y", pe_ratio_5y), ("PE vs 10y", pe_ratio_10y)):
        if ratio and ratio >= review_ratio:
            stretch_signals += 1
            reasons.append(f"{name} elevated ({ratio:.2f}x)")

    if valuation_percentile is not None and valuation_percentile >= 0.8:
        stretch_signals += 1
        reasons.append(f"valuation percentile high ({valuation_percentile:.0%})")

    if stretch_signals == 0:
        return AlertClassification(triggered=True, tier="Tier 1: Watch", reasons=reasons)

    if stretch_signals >= 2 and any((r and r >= deep_ratio) for r in (pe_ratio_3y, pe_ratio_5y, pe_ratio_10y)) and evidence_strength < 0.5:
        reasons.append("weak fundamental support for rerating")
        return AlertClassification(triggered=True, tier="Tier 3: Deep Review", reasons=reasons)

    return AlertClassification(triggered=True, tier="Tier 2: Review", reasons=reasons)
