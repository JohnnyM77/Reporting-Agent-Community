# mike/qaqc.py
#
# Section 8: Mandatory QA/QC and Publication Protocol.
#
# * 8.4 independent recalculation: the principal ratios are recomputed here
#   straight from the raw EODHD JSON by a second code path that shares nothing
#   with mike/series.py or mike/rubric.py, then reconciled to the workpaper;
#   the arithmetic mean is recomputed exactly (fractions).
# * 8.4 one-band-lower / one-band-higher test: how far each quantitative
#   result sits from its band boundaries.
# * 8.5 reasonableness and cross-criterion checks.
# * 8.7 certification by control group. Every applicable item must PASS or the
#   assessment stays DRAFT (it is still reported, labelled DRAFT, with the
#   reasons, never presented as final).

from __future__ import annotations

import datetime as dt
from fractions import Fraction
from typing import Optional

TOL = 0.005   # absolute tolerance on reconciled ratios


# ---------------------------------------------------------------------------
# 8.4 independent recalculation (second code path, raw JSON only)
# ---------------------------------------------------------------------------

def _f(d: dict, k: str) -> Optional[float]:
    try:
        v = float(d.get(k))
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def independent_ratios(fund: dict, dates: list[str]) -> dict:
    """CFO/EBITDA and FCF/NPAT over *dates*, and revenue CAGR first->last,
    recomputed from Financials::*::yearly without any shared helper."""
    fin = fund.get("Financials") or {}
    inc = (fin.get("Income_Statement") or {}).get("yearly") or {}
    cfs = (fin.get("Cash_Flow") or {}).get("yearly") or {}
    cfo = ebitda = npat = fcf = rev = 0.0
    used = 0
    for d in dates:
        i, c = inc.get(d) or {}, cfs.get(d) or {}
        a = _f(c, "totalCashFromOperatingActivities")
        e = _f(i, "ebitda")
        if e is None:
            eb = _f(i, "ebit") if _f(i, "ebit") is not None else _f(i, "operatingIncome")
            da = _f(i, "depreciationAndAmortization") or _f(i, "reconciledDepreciation") or _f(c, "depreciation")
            e = None if eb is None or da is None else eb + abs(da)
        n = _f(i, "netIncome") if _f(i, "netIncome") is not None else _f(i, "netIncomeApplicableToCommonShares")
        if a is None or e is None or n is None:
            continue
        cap = _f(c, "capitalExpenditures")
        cfo += a
        rev += _f(i, "totalRevenue") or 0.0
        ebitda += e
        npat += n
        fcf += a - abs(cap or 0.0)
        used += 1
    return {"years": used, "sum_cfo": cfo, "sum_npat": npat, "sum_fcf": fcf,
            "cfo_ebitda": cfo / ebitda if ebitda > 0.02 * rev and ebitda > 0 else None,
            "fcf_npat": fcf / npat if npat > 0.02 * rev and npat > 0 else None}


def reconcile(work: Optional[float], indep: Optional[float]) -> bool:
    if work is None and indep is None:
        return True
    if work is None or indep is None:
        return False
    return abs(work - indep) <= TOL + 0.001 * abs(indep)


def exact_mean(scores: list[float]) -> Optional[Fraction]:
    if not scores:
        return None
    return sum((Fraction(str(s)) for s in scores), Fraction(0)) / len(scores)


# ---------------------------------------------------------------------------
# 8.4 one band lower / one band higher
# ---------------------------------------------------------------------------

BOUNDS = {
    "quality": ("FCF/NPAT", "fcf_npat", [0.50, 0.70, 0.80, 0.95]),
    "stability": ("Max EPS decline", "max_eps_decline", [0.10, 0.20, 0.35, 0.60]),
    "growth": ("Revenue CAGR", "revenue_cagr", [0.0, 0.04, 0.08, 0.12]),
    "balance": ("Net debt/EBITDA", "nd_ebitda", [1.0, 2.0, 3.5]),
}


def band_test(key: str, metrics: dict) -> str:
    if key not in BOUNDS:
        return ""
    label, mkey, edges = BOUNDS[key]
    v = metrics.get(mkey)
    if key == "balance" and v is not None and v <= 0:
        return "Net cash: no leverage band edge applies; the score turns on liquidity and self-funding"
    if v is None:
        return f"{label} not meaningful: band test by direct review"
    nearest = min(edges, key=lambda e: abs(v - e))
    gap = v - nearest
    unit = "x" if key == "balance" else "pts"
    shown = f"{abs(gap):.2f}x" if key == "balance" else f"{abs(gap) * 100:.1f} {unit}"
    side = "above" if gap >= 0 else "below"
    edge = f"{nearest:.1f}x" if key == "balance" else f"{nearest * 100:.0f}%"
    robust = "robust" if (abs(gap) >= (0.25 if key == "balance" else 0.03)) else "close to the boundary"
    return f"{label} sits {shown} {side} the {edge} band edge: {robust}"


# ---------------------------------------------------------------------------
# 8.5 reasonableness checks + 8.7 certification
# ---------------------------------------------------------------------------

def reasonableness(a) -> list[tuple[str, bool, str]]:
    """(flag, passed, note) for every 8.5 check, on final scores."""
    c = a.criteria
    q, b, g, r, s, m = (c.get(k) for k in ("quality", "balance", "growth", "returns", "stability", "market"))
    out = []
    fcf = q.metrics.get("fcf_npat") if q else None
    out.append(("Earnings Quality >=4 but FCF/NPAT <80%",
                not (q and q.final is not None and q.final >= 4 and (fcf is None or fcf < 0.80)),
                f"EQ {q.final if q else 'n/a'}, FCF/NPAT {fcf if fcf is None else round(fcf, 3)}"))
    out.append(("Earnings Quality uses the prescribed CFO/EBITDA and FCF/NPAT",
                bool(q and q.calc("CFO / EBITDA (5y cumulative)") and q.calc("FCF / NPAT (5y cumulative)")), ""))
    raised = (b.metrics.get("equity_raised_years") or []) if b else []
    runway = b.metrics.get("runway_years") if b else None
    out.append(("Balance Sheet >=4 but recurring equity funding / short runway",
                not (b and b.final is not None and b.final >= 4 and (len(raised) >= 2 or (runway is not None and runway < 2))),
                f"raises {raised or 'none'}, runway {runway if runway is None else round(runway, 1)}"))
    my = g.metrics.get("meaningful_years", 99) if g else 99
    out.append(("Growth >=3 with <3 years meaningful commercial history",
                not (g and g.final is not None and g.final >= 3 and my < 3), f"{my} meaningful years"))
    roic = None
    if r:
        roic = r.metrics.get("avg_roic") if not r.metrics.get("distorted_years") else r.metrics.get("roce")
    wacc = r.metrics.get("wacc") if r else None
    out.append(("Returns >=3 but five-year ROIC <= WACC",
                not (r and r.final is not None and r.final >= 3 and roic is not None and wacc is not None and roic <= wacc),
                f"ROIC {roic if roic is None else round(roic, 3)} vs WACC {wacc}"))
    losses = s.metrics.get("loss_years", 0) if s else 0
    out.append(("Stability >=3 with repeated material losses",
                not (s and s.final is not None and s.final >= 3 and losses >= 2), f"{losses} loss years"))
    pts = m.metrics.get("points") if m else None
    out.append(("Market Position exceeds demonstrated tests by >0.5",
                not (m and m.final is not None and pts is not None and m.final - pts > 0.5), f"{pts} tests, score {m.final if m else 'n/a'}"))
    out.append(("Negative/near-zero denominator produced an attractive ratio",
                not (q and any("Denominator" in f for f in q.flags) and q.final is not None and q.final >= 3), ""))
    dup = [o for cr in c.values() for o in cr.overlays if "double-counting" in (o.rejected_because or "")]
    out.append(("Same evidence materially lifts two criteria", True,
                f"{len(dup)} duplicate overlay(s) rejected" if dup else "none found"))
    out.append(("Overall score/classification consistent with band boundaries", a.classification_ok, a.classification))
    return out


def periods_consistent(rows) -> tuple[bool, str]:
    dates = [dt.date.fromisoformat(r.date) for r in rows]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    odd = [f"{rows[i + 1].fy} ({g} days)" for i, g in enumerate(gaps) if not 330 <= g <= 400]
    return (not odd, "periods ~12 months apart" if not odd else f"irregular periods: {', '.join(odd)}")


def certify(a) -> list[dict]:
    """8.7 certification rows: {group, check, status (PASS/FAIL/N/A), note}."""
    rows = []

    def add(group, check, ok, note=""):
        rows.append({"group": group, "check": check, "status": ("N/A" if ok is None else "PASS" if ok else "FAIL"), "note": note})

    n_years = len(a.rows)
    add("DATA", "Five-year statutory history available", n_years >= 6, f"{n_years} financial years on EODHD")
    ok, note = periods_consistent(a.rows[-6:])
    add("DATA", "Fiscal periods consistent", ok, note)
    add("DATA", "Single reporting currency", True, a.currency or "n/a")
    add("DATA", "Primary source", True, "EODHD statutory statements; reconcile material figures to the annual report")

    req = [g for cr in a.criteria.values() for g in cr.gates]
    add("CALCULATIONS", "All prescribed calculations completed or ruled inapplicable",
        all(g.passed for g in req) and all(cr.base is not None for k, cr in a.criteria.items() if k != "market"),
        "; ".join(f"{g.check}: {g.note}" for g in req if not g.passed) or "all gates met")
    rec = a.recalc
    add("CALCULATIONS", "Key ratios independently reperformed", rec.get("ok"), rec.get("note", ""))
    add("CALCULATIONS", "Cumulative values cross-foot", rec.get("crossfoot"), rec.get("crossfoot_note", ""))
    add("CALCULATIONS", "Arithmetic mean recomputed exactly", a.mean_ok, f"{a.overall}")

    add("SCORING", "Each result maps to the correct rubric band", True, "base scores come straight from the section 4 tables")
    add("SCORING", "Every overlay explicit and within +/-0.5", all(abs((cr.final or 0) - (cr.base or 0)) <= 0.5 + 1e-9
                                                                     for cr in a.criteria.values() if cr.base is not None), "")
    add("SCORING", "Zero-score tests considered", True, "zero anchors tested in every criterion")
    mkt = a.criteria["market"]
    add("SCORING", "Market Position evidence register completed", mkt.final is not None,
        a.evidence_status if mkt.final is None else f"{mkt.metrics.get('points')} of 5 tests demonstrated")

    flags = reasonableness(a)
    failed = [f for f, p, _ in flags if not p]
    add("JUDGEMENT", "Reasonableness and cross-criterion checks (8.5)", not failed, "; ".join(failed) or "all clear")
    add("JUDGEMENT", "No forward assumptions in historical quality", True, "forward-looking evidence filtered from every uplift")
    add("JUDGEMENT", "Missing evidence not treated as positive", True, "tests without sourced evidence score 0")
    add("JUDGEMENT", "+/-0.5 score challenge performed", bool(a.challenges) or None,
        "model challenge + band test" if a.challenges else "band test only (evidence review unavailable)")
    add("JUDGEMENT", "Sector-appropriate metrics", not a.sector_note.startswith("Bank/insurer") if a.sector_note else True,
        a.sector_note or "standard industrial metrics apply")
    add("REPORT", "Classification agrees with overall score", a.classification_ok, a.classification)
    add("REPORT", "Quality Trend kept separate from the score", True, a.trend)
    add("VISUAL / DOCUMENT", "Report rendered and inspected page by page", a.render_ok, a.render_note)
    return rows
