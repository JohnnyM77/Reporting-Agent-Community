# mike/trend.py
#
# Quality Trend (framework section 6): Improving / Stable / Deteriorating,
# reported beside the score and never folded into it. Recent 2-3 years
# against the preceding period, reported results only.

from __future__ import annotations

import statistics
from typing import Optional

from mike.rubric import pct
from mike.series import YearRow

# A change smaller than this is not "material".
MATERIAL = {"ebit_margin": 0.03, "cash_conversion": 0.10, "roic": 0.03, "revenue_growth": 0.05, "leverage": 0.75}


def _mean(xs: list[Optional[float]]) -> Optional[float]:
    v = [x for x in xs if x is not None]
    return statistics.mean(v) if v else None


def _clip(x: Optional[float], lo: float = -1.0, hi: float = 1.0) -> Optional[float]:
    return None if x is None else max(lo, min(hi, x))


def _growth(rows: list[YearRow]) -> list[Optional[float]]:
    out = []
    for a, b in zip(rows, rows[1:]):
        out.append(_clip(b.revenue / a.revenue - 1, -1.0, 2.0) if (a.revenue and b.revenue and a.revenue > 0) else None)
    return out


def _roic(rows: list[YearRow]) -> list[Optional[float]]:
    out = []
    for a, b in zip(rows, rows[1:]):
        if b.nopat is None or a.invested_capital is None or b.invested_capital is None:
            out.append(None)
            continue
        ic = (a.invested_capital + b.invested_capital) / 2
        out.append(max(-1.0, min(1.0, b.nopat / ic)) if ic > 0 else None)
    return out


def quality_trend(rows: list[YearRow]) -> tuple[str, list[str]]:
    if len(rows) < 6:
        return "Stable", [f"Only {len(rows)} years on EODHD: too short to show a demonstrated change"]
    recent, prior = rows[-3:], rows[-6:-3]
    rec_g, pri_g = _growth(rows[-4:]), _growth(rows[-7:-3] if len(rows) >= 7 else rows[-6:-3])
    rec_r, pri_r = _roic(rows[-4:]), _roic(rows[-7:-3] if len(rows) >= 7 else rows[-6:-3])

    def conv(rs):
        return _mean([r.cfo / r.ebitda for r in rs if r.cfo is not None and r.ebitda and r.ebitda > 0])

    def lev(rs):
        return _mean([r.net_debt / r.ebitda for r in rs if r.net_debt is not None and r.ebitda and r.ebitda > 0])

    tests = [
        ("EBIT margin", _mean([_clip(r.ebit_margin) for r in prior]), _mean([_clip(r.ebit_margin) for r in recent]), MATERIAL["ebit_margin"], True),
        ("Cash conversion (CFO/EBITDA)", conv(prior), conv(recent), MATERIAL["cash_conversion"], True),
        ("ROIC", _mean(pri_r), _mean(rec_r), MATERIAL["roic"], True),
        ("Revenue growth", _mean(pri_g), _mean(rec_g), MATERIAL["revenue_growth"], True),
        ("Net debt / EBITDA", lev(prior), lev(recent), MATERIAL["leverage"], False),
    ]
    up, down, notes = 0, 0, []
    for name, before, after, thr, higher_better in tests:
        if before is None or after is None:
            continue
        d = after - before
        if abs(d) < thr:
            continue
        better = d > 0 if higher_better else d < 0
        up += better
        down += not better
        fmt = (lambda x: f"{x:.1f}x") if name.startswith("Net debt") else (lambda x: pct(x, 1))
        notes.append(f"{name} {'improved' if better else 'weakened'}: {fmt(before)} ({prior[0].fy}-{prior[-1].fy}) "
                     f"to {fmt(after)} ({recent[0].fy}-{recent[-1].fy})")
    # Recent losses where the prior period was profitable count as deterioration.
    if any(r.npat is not None and r.npat < 0 for r in recent) and all(r.npat and r.npat > 0 for r in prior):
        down += 1
        notes.append("Statutory loss in the recent period after a profitable prior period")
    if up - down >= 2:
        label = "Improving"
    elif down - up >= 2:
        label = "Deteriorating"
    else:
        label = "Stable"
    if not notes:
        notes.append("No material change between the two three-year periods")
    return label, notes
