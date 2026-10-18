"""The value wedge: a moving BUY/SELL corridor built from time-dependent EPS
and time-dependent PE multiples.

    BUY value  = EPS in force on that date x BUY PE in force on that date
    SELL value = EPS in force on that date x SELL PE in force on that date

Two forces move the corridor and this module keeps them apart:

* EPS changes shift the whole corridor up or down. The relative wedge
  (SELL PE / BUY PE - 1) does not move.
* Multiple changes widen, narrow, lift or lower the corridor with EPS
  unchanged. Only these move the relative wedge.

Nothing here is company-specific. Inputs are an earnings history, a
multiple history, a price series and optional notes; ``load_wedge_inputs``
builds them from ``valuations/<slug>.yaml`` (and git history of that file,
and the thesis file) for any ticker.

No look-ahead: an EPS figure applies from its release date onwards and never
before it. The earliest multiple regime is applied to the start of the
history because there was no earlier framework, and the chart says so.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

EPS_BASIS_LABELS = {
    "reported_ttm": "Reported EPS, trailing 12 months",
    "normalised": "Normalised EPS, trailing 12 months",
    "forward": "FORWARD EPS (next 12 months)",
}

# An EPS move smaller than this is not annotated as a corridor shift.
EPS_EVENT_THRESHOLD = 0.10
# 52-week window in trading days.
_HIGH_WINDOW = 252


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class EarningsPoint:
    date: dt.date            # release date: the day the market could know it
    period: str
    eps_cents: float         # reported (or forward, per eps_basis)
    norm_eps_cents: float | None = None
    source: str = ""
    notes: str = ""

    @property
    def eps_used(self) -> float:
        return self.norm_eps_cents if self.norm_eps_cents is not None else self.eps_cents


@dataclass
class MultipleRegime:
    date: dt.date
    buy_pe: float
    sell_pe: float
    reason: str = ""
    source: str = "config"

    @property
    def relative_wedge(self) -> float:
        return self.sell_pe / self.buy_pe - 1


@dataclass
class Note:
    date: dt.date
    label: str
    kind: str = "note"       # note | thesis


@dataclass
class WedgeInputs:
    ticker: str
    company_name: str
    currency: str
    eps_basis: str
    earnings: list[EarningsPoint]
    multiples: list[MultipleRegime]
    prices: pd.Series                     # daily close, DatetimeIndex
    notes: list[Note] = field(default_factory=list)
    multiples_source: str = "config"
    warnings: list[str] = field(default_factory=list)
    period_notes: dict[str, str] = field(default_factory=dict)
    # EPS reported in a different currency from the share price (BHP: US$ EPS,
    # A$ price): ``fx`` is trading-currency units per one EPS-currency unit,
    # daily, and every week's EPS is converted at that week's rate.
    eps_currency: str = ""
    fx: pd.Series | None = None           # converted at the rate on each result's release date
    fx_label: str = ""
    fy_end_month: int = 6
    # Where "fair value" sits inside the wedge: 0.3 = 30% of the way from BUY
    # to SELL (buy well below value, sell well above it). None = no fair line.
    fair_split: float | None = 0.3
    smoothing: str = ""                  # human description when EPS is smoothed
    # Periods where statutory EPS understates earning power (e.g. PWH's factory
    # relocation): [{"start", "end", "label", "reference_period",
    # "reference_eps"}]. Drawn as a band with a faint reference corridor on the
    # named reported year's EPS; the wedge itself stays on statutory EPS.
    depressed: list[dict] = field(default_factory=list)
    start: dt.date | None = None         # first date shown (history before it still feeds 52w highs)
    # Forward EPS (NOT reported): [{"period", "date", "eps_cents", "note"}],
    # oldest first. Drawn to the right of today as a lighter corridor; never
    # mixed into the reported history, the zones or the alerts.
    forecast: list[dict] = field(default_factory=list)
    forecast_label: str = ""
    forecast_basis: str = ""
    forecast_end: dt.date | None = None
    # [{"label", "basis"}] in drawing order; each forecast row carries "case".
    forecast_cases: list[dict] = field(default_factory=list)
    # {"as_of", "recover": [...], "not_recover": [...], "note"}: the case for
    # and against a recovery, printed in the email and memo (valuation YAML).
    outlook: dict = field(default_factory=dict)
    # Where the BUY multiple came from when it is the archetype's (else "").
    multiple_note: str = ""

    @property
    def eps_basis_label(self) -> str:
        return EPS_BASIS_LABELS.get(self.eps_basis, self.eps_basis)


@dataclass
class WedgePoint:
    date: dt.date
    price: float
    period: str | None
    reported_eps: float | None
    normalised_eps: float | None
    eps_used: float | None
    eps_source: str | None
    buy_pe: float | None
    sell_pe: float | None
    buy_value: float | None
    sell_value: float | None
    actual_pe: float | None
    abs_wedge: float | None
    rel_wedge: float | None
    position: float | None               # 0 = on BUY, 1 = on SELL
    zone: str
    new_52w_high: bool = False
    fx: float | None = None               # trading ccy per EPS ccy unit (None = same currency)
    fair_pe: float | None = None
    fair_value: float | None = None


@dataclass
class CorridorEvent:
    date: dt.date
    kind: str                            # earnings | multiple | note | thesis
    text: str


@dataclass
class WedgeResult:
    inputs: WedgeInputs
    points: list[WedgePoint]
    events: list[CorridorEvent]
    current: WedgePoint | None
    near_52w_high: bool
    diagnostics: list[tuple[str, str]]
    headline: str
    # One row per forecast period: BUY / fair / SELL on that EPS at the
    # current multiples, and where today's price sits against it.
    forecast: list[dict] = field(default_factory=list)
    # {"years": N or None, "lows": {"1": low, ...}, "since": date or None,
    #  "first": first date of the history}: is today a multi-year low?
    price_low: dict | None = None

    def to_dict(self) -> dict:
        cur = self.current
        return {
            "ticker": self.inputs.ticker,
            "company_name": self.inputs.company_name,
            "currency": self.inputs.currency,
            "eps_basis": self.inputs.eps_basis_label,
            "multiples_source": self.inputs.multiples_source,
            "headline": self.headline,
            "current": _point_dict(cur) if cur else None,
            "near_52w_high": self.near_52w_high,
            "diagnostics": [{"question": q, "answer": a} for q, a in self.diagnostics],
            "events": [{"date": e.date.isoformat(), "kind": e.kind, "text": e.text} for e in self.events],
            "multiple_history": [
                {"date": m.date.isoformat(), "buy_pe": m.buy_pe, "sell_pe": m.sell_pe,
                 "reason": m.reason, "source": m.source}
                for m in self.inputs.multiples
            ],
            "earnings_history": [
                {"date": e.date.isoformat(), "period": e.period, "reported_eps": e.eps_cents,
                 "normalised_eps": e.norm_eps_cents, "source": e.source, "notes": e.notes}
                for e in self.inputs.earnings
            ],
            "warnings": list(self.inputs.warnings),
            "forecast": {"label": self.inputs.forecast_label, "basis": self.inputs.forecast_basis,
                         "cases": self.inputs.forecast_cases,
                         "rows": [{**r, "date": r["date"].isoformat()} for r in self.forecast]}
                        if self.forecast else None,
            "price_low": ({**self.price_low, "since": self.price_low["since"].isoformat()
                           if self.price_low.get("since") else None,
                           "first": self.price_low["first"].isoformat()}
                          if self.price_low else None),
            "low_line": low_line(self),
            "outlook": self.inputs.outlook or None,
        }

    def points_frame(self) -> pd.DataFrame:
        return pd.DataFrame([_point_dict(p) for p in self.points])


def _point_dict(p: WedgePoint) -> dict:
    d = asdict(p)
    d["date"] = p.date.isoformat()
    return d


# ── Core computation ────────────────────────────────────────────────────────

def zone_for(position: float | None) -> str:
    if position is None:
        return "No valuation"
    if position < 0:
        return "Below BUY"
    if position <= 1 / 3:
        return "Lower third of wedge"
    if position <= 2 / 3:
        return "Middle of wedge"
    if position <= 1:
        return "Upper third of wedge"
    return "Above SELL"


def _last_on_or_before(d: dt.date, items: list, attr: str = "date"):
    found = None
    for it in items:
        if getattr(it, attr) <= d:
            found = it
        else:
            break
    return found


def compute_wedge(inputs: WedgeInputs, *, freq: str = "W-FRI",
                  near_high_threshold: float = 0.05) -> WedgeResult:
    earnings = sorted(inputs.earnings, key=lambda e: e.date)
    multiples = sorted(inputs.multiples, key=lambda m: m.date)
    prices = inputs.prices.dropna().sort_index()
    if prices.empty:
        raise ValueError(f"{inputs.ticker}: no price history")

    roll_max = prices.rolling(_HIGH_WINDOW, min_periods=_HIGH_WINDOW).max()
    is_high = (prices >= roll_max) & roll_max.notna()

    weekly = prices.resample(freq).last().dropna()
    weekly_high = is_high.resample(freq).max().reindex(weekly.index).fillna(False)

    fx = None
    if inputs.eps_currency:
        if inputs.fx is None or inputs.fx.dropna().empty:
            raise ValueError(f"{inputs.ticker}: EPS is in {inputs.eps_currency} but no exchange-rate history")
        fx = inputs.fx.dropna().sort_index()

    def fx_at(ts) -> float | None:
        if fx is None:
            return None
        s = fx[fx.index <= ts]
        return float(s.iloc[-1]) if not s.empty else float(fx.iloc[0])

    points: list[WedgePoint] = []
    def fx_for(e):
        # Converted once, at the rate on the day the result came out, so BUY
        # and SELL stay flat until the next result (ASX: every six months).
        return fx_at(pd.Timestamp(e.date)) if e is not None else None

    for ts, close in weekly.items():
        d = ts.date()
        e = _last_on_or_before(d, earnings)
        m = _last_on_or_before(d, multiples) or (multiples[0] if multiples else None)
        points.append(_make_point(d, float(close), e, m, bool(weekly_high.loc[ts]), fx_for(e),
                                  inputs.fair_split))

    # The latest point uses the latest close, not the week-end resample, and
    # the framework in force today: a BUY/SELL change made over a weekend
    # applies to "now" without back-dating it onto Friday's history.
    last_ts = prices.index[-1]
    if points:
        e = _last_on_or_before(last_ts.date(), earnings)
        asof = max(last_ts.date(), dt.date.today())
        m = _last_on_or_before(asof, multiples) or (multiples[0] if multiples else None)
        points[-1] = _make_point(last_ts.date(), float(prices.iloc[-1]), e, m, bool(is_high.iloc[-1]),
                                 fx_for(e), inputs.fair_split)
    if inputs.start:
        points = [p for p in points if p.date >= inputs.start]

    current = points[-1] if points else None
    last_year = prices[prices.index >= last_ts - pd.Timedelta(days=365)]
    high_52w = float(last_year.max()) if not last_year.empty else None
    near_high = bool(high_52w and current and (high_52w - current.price) / high_52w <= near_high_threshold)

    events = _corridor_events(inputs, earnings, multiples, points)
    diagnostics = _diagnostics(inputs, points, near_high, high_52w)
    headline = _headline(inputs, current)
    forecast = _forecast_rows(inputs, multiples, current, fx_at(prices.index[-1]))
    return WedgeResult(inputs, points, events, current, near_high, diagnostics, headline, forecast,
                       _price_low(prices))


LOW_HORIZONS = (1, 2, 3, 5, 10)
LOW_BAND_PCT = 5.0


def _price_low(prices: pd.Series) -> dict | None:
    """Is today's close near a 1/2/3/5/10-year low (within 5%, Wally's band)?
    Uses every close the run fetched, which reaches back a year before the
    chart starts at least."""
    from shared.lows import lowest_since, multi_year_low
    if prices.empty:
        return None
    closes = [(ts.date(), float(v)) for ts, v in prices.items()]
    today, cur = closes[-1]
    years, lows = multi_year_low(cur, closes, today, LOW_BAND_PCT, LOW_HORIZONS)
    return {"years": years, "lows": lows, "since": lowest_since(cur, closes, today), "first": closes[0][0],
            "price": cur}


def low_line(result: "WedgeResult") -> str:
    """One line for the top of the chart and the email: how many years' low?"""
    pl = result.price_low
    if not pl:
        return ""
    cur, lows = pl["price"], pl["lows"]
    since = pl.get("since")
    since_txt = (f"lowest close since {since:%b %Y}" if since
                 else f"lowest close in the data (since {pl['first']:%b %Y})")
    longest = max(lows, key=int) if lows else None
    if pl.get("years"):
        y, lo = pl["years"], lows[str(pl["years"])]
        if cur <= lo * 1.005:
            return f"At its {y}-year low: ${cur:,.2f}, the " + since_txt + "."
        return f"Near its {y}-year low: ${cur:,.2f} vs ${lo:,.2f} ({(cur / lo - 1):+.0%}); " + since_txt + "."
    if longest:
        lo = lows[longest]
        return f"Not at a multi-year low: ${cur:,.2f} is {(cur / lo - 1):+.0%} above its {longest}-year low (${lo:,.2f})."
    return ""


def _forecast_rows(inputs: WedgeInputs, multiples: list[MultipleRegime], cur: WedgePoint | None,
                   fx_now: float | None) -> list[dict]:
    """BUY / fair / SELL on each forecast EPS, at the multiples in force today.
    The current price is compared with each, so 'where does the wedge travel
    to, and how far is today's price from it' reads straight off the table."""
    if not inputs.forecast or not multiples:
        return []
    m = multiples[-1]
    split = inputs.fair_split
    fair_pe = m.buy_pe + split * (m.sell_pe - m.buy_pe) if split is not None else None
    price = cur.price if cur else None
    out = []
    for f in inputs.forecast:
        eps = f.get("eps_basis_cents", f["eps_cents"]) * (fx_now or 1.0)
        buy, sell = eps * m.buy_pe / 100, eps * m.sell_pe / 100
        fair = eps * fair_pe / 100 if fair_pe else None
        pos = (price - buy) / (sell - buy) if (price is not None and sell > buy) else None
        out.append({**f, "eps_trading_ccy": eps, "buy_pe": m.buy_pe, "sell_pe": m.sell_pe, "fair_pe": fair_pe,
                    "buy_value": buy, "fair_value": fair, "sell_value": sell,
                    "price_today": price, "forward_pe_today": (price / (eps / 100)) if price and eps > 0 else None,
                    "position_today": pos, "zone_today": zone_for(pos)})
    return out


def forecast_lines(result: "WedgeResult") -> list[str]:
    """Plain-English forecast rows for the email, memo, log and Claude prompt."""
    out = []
    many = len(result.inputs.forecast_cases) > 1
    for r in result.forecast:
        pos = r.get("position_today")
        fwd = r.get("forward_pe_today")
        basis = (f" ({r['eps_basis_cents']:.1f}c on the wedge's basis)"
                 if r.get("eps_basis_cents") is not None and abs(r["eps_basis_cents"] - r["eps_cents"]) > 0.05 else "")
        out.append(
            (f"[{r.get('case')}] " if many else "")
            + f"{r['period']}F (expected {r['date']:%b %Y}): EPS {r['eps_cents']:.1f}c{basis} -> BUY {_money(r['buy_value'])}"
            + (f" / fair {_money(r['fair_value'])}" if r.get("fair_value") else "")
            + f" / SELL {_money(r['sell_value'])}. Today's price {_money(r['price_today'])} = "
            + (f"{fwd:.0f}x that EPS, " if fwd else "")
            + (f"{r['zone_today'].lower()} ({pos:.0%} BUY->SELL)" if pos is not None else "no position")
            + (f". {r['note']}" if r.get("note") else "")
        )
    return out


def forecast_corridor(result: "WedgeResult", case: str | None = None) -> pd.DataFrame:
    """Daily corridor from the day after the last close to ``forecast_end``:
    today's EPS until the first forecast release, then each forecast EPS from
    its expected release date. No price (it hasn't happened). ``case`` picks
    one scenario (default: the first)."""
    inp = result.inputs
    if not result.forecast or result.current is None:
        return pd.DataFrame()
    case = case or (inp.forecast_cases[0]["label"] if inp.forecast_cases else None)
    fc = [r for r in result.forecast if case is None or r.get("case") == case]
    if not fc:
        return pd.DataFrame()
    last = pd.Timestamp(result.current.date)
    end = pd.Timestamp(inp.forecast_end or (pd.Timestamp(max(r["date"] for r in result.forecast))
                                            + pd.DateOffset(months=6)))
    idx = pd.bdate_range(last + pd.Timedelta(days=1), end)
    cur = result.current
    rows = []
    for ts in idx:
        f = next((r for r in reversed(fc) if pd.Timestamp(r["date"]) <= ts), None)
        if f is None:
            rows.append({"date": ts, "eps": cur.eps_used, "buy": cur.buy_value, "sell": cur.sell_value,
                         "fair": cur.fair_value, "buy_pe": cur.buy_pe, "sell_pe": cur.sell_pe,
                         "fair_pe": cur.fair_pe, "period": cur.period})
        else:
            rows.append({"date": ts, "eps": f["eps_trading_ccy"], "buy": f["buy_value"], "sell": f["sell_value"],
                         "fair": f["fair_value"], "buy_pe": f["buy_pe"], "sell_pe": f["sell_pe"],
                         "fair_pe": f["fair_pe"], "period": f["period"]})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def daily_corridor(result: "WedgeResult") -> pd.DataFrame:
    """Daily close with the BUY/SELL corridor in force that day.

    BUY and SELL change only on a release date (or a multiple change), so they
    are flat between results; the price is every real daily close.
    """
    inp = result.inputs
    earnings = sorted(inp.earnings, key=lambda e: e.date)
    multiples = sorted(inp.multiples, key=lambda m: m.date)
    prices = inp.prices.dropna().sort_index()
    if inp.start:
        prices = prices[prices.index >= pd.Timestamp(inp.start)]
    fx = inp.fx.dropna().sort_index() if (inp.eps_currency and inp.fx is not None) else None

    def fx_on(d: dt.date) -> float | None:
        if fx is None:
            return None
        s = fx[fx.index <= pd.Timestamp(d)]
        return float(s.iloc[-1]) if not s.empty else float(fx.iloc[0])

    fx_cache: dict = {}
    rows = []
    for ts, close in prices.items():
        d = ts.date()
        e = _last_on_or_before(d, earnings)
        m = _last_on_or_before(d, multiples) or (multiples[0] if multiples else None)
        rate = None
        if e is not None and fx is not None:
            rate = fx_cache.setdefault(e.date, fx_on(e.date))
        pt = _make_point(d, float(close), e, m, False, rate, inp.fair_split)
        rep = (e.eps_cents * (rate or 1.0)) if e is not None else None
        rep_ok = rep is not None and rep > 0 and m is not None
        rows.append({"date": ts, "price": pt.price, "eps": pt.eps_used, "buy": pt.buy_value,
                     "sell": pt.sell_value, "fair": pt.fair_value, "pe": pt.actual_pe,
                     "buy_pe": pt.buy_pe, "sell_pe": pt.sell_pe, "fair_pe": pt.fair_pe,
                     "eps_reported": rep,
                     "buy_reported": rep * m.buy_pe / 100 if rep_ok else None,
                     "sell_reported": rep * m.sell_pe / 100 if rep_ok else None,
                     "pe_reported": float(close) / (rep / 100) if (rep is not None and rep > 0) else None})
    return pd.DataFrame(rows).set_index("date")


def _make_point(d: dt.date, close: float, e: EarningsPoint | None,
                m: MultipleRegime | None, high: bool, fx: float | None = None,
                fair_split: float | None = None) -> WedgePoint:
    eps = e.eps_used if e else None
    if eps is not None and fx is not None:
        eps = eps * fx                    # into the share price's currency
    usable = eps is not None and eps > 0 and m is not None
    buy = eps * m.buy_pe / 100 if usable else None
    sell = eps * m.sell_pe / 100 if usable else None
    pe = close / (eps / 100) if (eps is not None and eps > 0) else None
    pos = (close - buy) / (sell - buy) if (usable and sell > buy) else None
    fair_pe = (m.buy_pe + fair_split * (m.sell_pe - m.buy_pe)) if (m and fair_split is not None) else None
    fair = eps * fair_pe / 100 if (usable and fair_pe) else None
    return WedgePoint(
        date=d, price=close,
        period=e.period if e else None,
        reported_eps=e.eps_cents if e else None,
        normalised_eps=e.norm_eps_cents if e else None,
        eps_used=eps,
        eps_source=e.source if e else None,
        buy_pe=m.buy_pe if m else None,
        sell_pe=m.sell_pe if m else None,
        buy_value=buy, sell_value=sell, actual_pe=pe,
        abs_wedge=(sell - buy) if usable else None,
        rel_wedge=m.relative_wedge if m else None,
        position=pos, zone=zone_for(pos), new_52w_high=high, fx=fx,
        fair_pe=fair_pe, fair_value=fair,
    )


# ── Narrative: why the corridor moved ───────────────────────────────────────

def _money(v: float | None, ccy: str = "") -> str:
    if v is None:
        return "n/a"
    return f"{ccy}${v:,.2f}"


def _pct(v: float | None, signed: bool = True) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "n/a"
    return f"{v:+.0%}" if signed else f"{v:.0%}"


def _corridor_events(inputs: WedgeInputs, earnings: list[EarningsPoint],
                     multiples: list[MultipleRegime],
                     points: list[WedgePoint]) -> list[CorridorEvent]:
    if not points:
        return []
    start, end = points[0].date, points[-1].date
    events: list[CorridorEvent] = []

    unit = ("smoothed " if inputs.smoothing else "") + (f"{inputs.eps_currency} " if inputs.eps_currency else "")
    for prev, cur in zip(earnings, earnings[1:]):
        if not (start < cur.date <= end):
            continue
        a, b = prev.eps_used, cur.eps_used
        if a is None or b is None:
            continue
        before = next((p for p in reversed(points) if p.date < cur.date), None)
        after = next((p for p in points if p.date >= cur.date), None)
        if a <= 0 or b <= 0:
            if a > 0 >= b:
                text = (f"{cur.period}: EPS turned to a loss ({unit}{a:.1f}c -> {b:.1f}c) -> no PE-based "
                        "value while earnings are negative; the corridor disappears")
            elif a <= 0 < b:
                text = (f"{cur.period}: EPS back to a profit ({unit}{a:.1f}c -> {b:.1f}c) -> the corridor "
                        f"resumes at BUY {_money(after.buy_value if after else None)} / "
                        f"SELL {_money(after.sell_value if after else None)}")
            else:
                text = f"{cur.period}: still a loss ({unit}{a:.1f}c -> {b:.1f}c) -> no PE-based value"
        else:
            chg = b / a - 1
            if abs(chg) < EPS_EVENT_THRESHOLD:
                continue
            direction = "rose" if chg > 0 else "fell"
            shift = "upward" if chg > 0 else "downward"
            moved = (after.buy_value - before.buy_value) if (before and after and before.buy_value
                                                            and after.buy_value) else None
            if moved is not None and (moved > 0) != (chg > 0):
                # The exchange rate at this release more than offset the EPS move.
                shift = ("upward" if moved > 0 else "downward") + " (the exchange rate outweighed the EPS move)"
            text = (f"{cur.period}: {unit}EPS {direction} {abs(chg):.0%} ({a:.1f}c -> {b:.1f}c) "
                    f"-> valuation corridor shifted {shift}")
            if moved is not None:
                text += (f" (BUY {_money(before.buy_value)} -> {_money(after.buy_value)}, "
                         f"SELL {_money(before.sell_value)} -> {_money(after.sell_value)}); "
                         "relative wedge unchanged")
        context = (inputs.period_notes.get(cur.period.upper())
                   or inputs.period_notes.get(cur.period.replace(" TTM", "").upper()))
        if context:
            text += f". {context}"
        elif cur.notes and "|" in cur.notes and "smoothed" not in cur.notes.split("|", 1)[1]:
            text += f". {cur.notes.split('|', 1)[1].strip()}"
        events.append(CorridorEvent(cur.date, "earnings", text))

    for prev, cur in zip(multiples, multiples[1:]):
        parts = []
        if cur.buy_pe != prev.buy_pe:
            parts.append(f"BUY multiple {'increased' if cur.buy_pe > prev.buy_pe else 'cut'} "
                         f"from {prev.buy_pe:g}x to {cur.buy_pe:g}x")
        if cur.sell_pe != prev.sell_pe:
            parts.append(f"SELL multiple {'increased' if cur.sell_pe > prev.sell_pe else 'cut'} "
                         f"from {prev.sell_pe:g}x to {cur.sell_pe:g}x")
        if not parts:
            continue
        rw_a, rw_b = prev.relative_wedge, cur.relative_wedge
        if abs(rw_b - rw_a) < 0.005:
            shape = "corridor " + ("lifted" if cur.buy_pe > prev.buy_pe else "lowered") + \
                    f" with its relative width unchanged at {rw_b:.0%}"
        else:
            shape = ("corridor widened" if rw_b > rw_a else "corridor narrowed") + \
                    f" (relative wedge {rw_a:.0%} -> {rw_b:.0%})"
        text = " and ".join(parts) + f" -> {shape}. A valuation-framework change, not an earnings change"
        if cur.reason:
            text += f". Why: {cur.reason}"
        events.append(CorridorEvent(cur.date, "multiple", text))

    for n in inputs.notes:
        if start <= n.date <= end:
            events.append(CorridorEvent(n.date, n.kind, n.label))

    events.sort(key=lambda e: e.date)
    return events


# ── Diagnostics: the seven questions ────────────────────────────────────────

def _point_near(points: list[WedgePoint], target: dt.date) -> WedgePoint | None:
    best = None
    for p in points:
        if p.buy_value is None:
            continue
        if p.date <= target:
            best = p
        elif best is None:
            return p
        else:
            break
    return best


def _ratio(a: float | None, b: float | None) -> float | None:
    if a in (None, 0) or b is None:
        return None
    return b / a - 1


def _since_date(points: list[WedgePoint], test) -> dt.date | None:
    """First date of the current unbroken run where test(point) holds."""
    since = None
    for p in reversed(points):
        if p.position is None or not test(p):
            break
        since = p.date
    return since


def _diagnostics(inputs: WedgeInputs, points: list[WedgePoint], near_high: bool,
                 high_52w: float | None) -> list[tuple[str, str]]:
    name = inputs.ticker.split(".")[0]
    cur = points[-1] if points else None
    if cur is None or cur.buy_value is None:
        return [("Valuation", "No usable EPS / multiple at the latest date, so no wedge can be drawn.")]

    first = _point_near(points, points[0].date)
    anchor = _point_near(points, cur.date - dt.timedelta(days=3 * 365))
    if anchor is None or anchor.date == cur.date:
        anchor = first
    span = f"since {anchor.date:%b %Y}"

    eps_g = _ratio(anchor.eps_used, cur.eps_used)
    eps_lbl = ("smoothed " if inputs.smoothing else "") + (f"{inputs.currency or ''}$ EPS" if inputs.eps_currency else "EPS")
    buype_g = _ratio(anchor.buy_pe, cur.buy_pe)
    buy_g = _ratio(anchor.buy_value, cur.buy_value)
    sell_g = _ratio(anchor.sell_value, cur.sell_value)
    price_g = _ratio(anchor.price, cur.price)
    pe_g = _ratio(anchor.actual_pe, cur.actual_pe)

    out: list[tuple[str, str]] = []

    # 1. More valuable because earnings rose?
    if eps_g is None:
        a1 = "EPS comparison unavailable."
    elif eps_g > 0.02:
        a1 = (f"Yes: {eps_lbl} {_pct(eps_g)} {span} ({anchor.eps_used:.1f}c -> {cur.eps_used:.1f}c), "
              f"so the corridor moved {_pct(buy_g)} (BUY {_money(anchor.buy_value)} -> {_money(cur.buy_value)}).")
    elif eps_g < -0.02:
        a1 = (f"No: {eps_lbl} {_pct(eps_g)} {span} ({anchor.eps_used:.1f}c -> {cur.eps_used:.1f}c), "
              f"so the corridor moved {_pct(buy_g)} (BUY {_money(anchor.buy_value)} -> {_money(cur.buy_value)}).")
    else:
        a1 = f"Flat: EPS {_pct(eps_g)} {span}; the business is worth about the same on this measure."
    full_eps = _ratio(first.eps_used, cur.eps_used) if first else None
    if first and first.date != anchor.date and full_eps is not None:
        a1 += f" Over the full history ({first.date:%b %Y}) EPS is {_pct(full_eps)}."
    if inputs.eps_currency and anchor.fx and cur.fx:
        rep_g = _ratio(anchor.reported_eps, cur.reported_eps)
        a1 += (f" Those are {inputs.currency or ''}$ figures: reported {inputs.eps_currency} EPS moved "
               f"{_pct(rep_g)} and the exchange rate {_pct(cur.fx / anchor.fx - 1)} ({inputs.fx_label}).")
    out.append((f"Has {name} become more valuable because earnings increased?", a1))

    # 2. Range widened / narrowed?
    rw_a, rw_b = anchor.rel_wedge, cur.rel_wedge
    if rw_a is None or rw_b is None:
        a2 = "Multiple history unavailable."
    elif abs(rw_b - rw_a) < 0.005:
        a2 = (f"No. The relative wedge is unchanged at {rw_b:.0%} (SELL {cur.sell_pe:g}x / BUY {cur.buy_pe:g}x). "
              f"The dollar wedge moved {_money(anchor.abs_wedge)} -> {_money(cur.abs_wedge)} only because EPS moved.")
    else:
        a2 = (f"{'Widened' if rw_b > rw_a else 'Narrowed'}: relative wedge {rw_a:.0%} -> {rw_b:.0%} {span} "
              f"(BUY {anchor.buy_pe:g}x -> {cur.buy_pe:g}x, SELL {anchor.sell_pe:g}x -> {cur.sell_pe:g}x). "
              "That is a change in the valuation framework.")
    if inputs.multiples_source == "config":
        a2 += " The multiples have never been changed in the config, so no historical change is shown."
    out.append(("Has the valuation range itself widened or narrowed?", a2))

    # 3. Price faster than the corridor?
    if price_g is None or buy_g is None:
        a3 = "Price/value comparison unavailable."
    else:
        gap = (1 + price_g) / (1 + buy_g) - 1
        verdict = "faster than" if gap > 0.05 else ("slower than" if gap < -0.05 else "in line with")
        a3 = (f"Price {_pct(price_g)} vs corridor {_pct(buy_g)} {span}: price has moved {verdict} value. ")
        if pe_g is not None and anchor.actual_pe and cur.actual_pe:
            a3 += (f"The difference is the market multiple: actual PE {anchor.actual_pe:.0f}x -> "
                   f"{cur.actual_pe:.0f}x ({_pct(pe_g)}), while EPS moved {_pct(eps_g)}.")
    out.append(("Has the market price risen faster than the valuation corridor?", a3))

    # 4 & 5. Inside the wedge? Above SELL?
    pos = cur.position
    if pos is None:
        a4 = a5 = "Not computable."
    else:
        a4 = (f"{cur.zone}: price {_money(cur.price)} vs BUY {_money(cur.buy_value)} / SELL {_money(cur.sell_value)} "
              f"= {pos:.0%} of the way from BUY to SELL.")
        since_in = _since_date(points, lambda p: p.position is not None and p.position >= 0)
        if 0 <= pos <= 1 and since_in:
            a4 += f" Inside or above the wedge since {since_in:%d %b %Y}."
        if pos > 1:
            since = _since_date(points, lambda p: p.position is not None and p.position > 1)
            a5 = (f"Yes. Price is {cur.price / cur.sell_value - 1:.0%} above the SELL value; actual PE "
                  f"{cur.actual_pe:.0f}x vs SELL {cur.sell_pe:g}x"
                  + (f", continuously since {since:%d %b %Y}." if since else "."))
        else:
            room = cur.sell_value / cur.price - 1
            a5 = f"No. SELL is {_money(cur.sell_value)}, {room:.0%} above the current price."
    out.append(("Has the market price entered the WEDGE?", a4))
    out.append(("Has it crossed the SELL boundary?", a5))

    # 6. BUY boundary risen because the business became more valuable?
    if buy_g is None or eps_g is None:
        a6 = "Unavailable."
    else:
        mult_part = buype_g or 0.0
        if abs(mult_part) < 0.005:
            a6 = (f"BUY moved {_pct(buy_g)} {span}, all of it from EPS ({_pct(eps_g)}); the BUY multiple is "
                  f"unchanged at {cur.buy_pe:g}x. "
                  + ("The business is worth more." if buy_g > 0 else "The business is worth less on this measure."))
        else:
            a6 = (f"BUY moved {_pct(buy_g)} {span}: EPS {_pct(eps_g)} and BUY multiple {_pct(buype_g)} "
                  f"({anchor.buy_pe:g}x -> {cur.buy_pe:g}x). Only the EPS part is the business becoming more valuable.")
    out.append(("Has the BUY boundary risen because the underlying business became more valuable?", a6))

    # 7. Genuine stretch or just a 52-week high?
    pe_txt = f"{cur.actual_pe:.0f}x" if cur.actual_pe else "n/a"
    hi_txt = (f"Price is within 5% of the 52-week high ({_money(high_52w)})" if near_high
              else f"Price is not near the 52-week high ({_money(high_52w)})")
    if pos is None:
        a7 = hi_txt + "; no wedge to test against."
    elif pos > 1:
        a7 = (hi_txt + f", and the PE ({pe_txt}) is above the SELL multiple ({cur.sell_pe:g}x). "
              + ("Both fired: the stretch is genuine valuation, not just price momentum."
                 if near_high else "The valuation stretch stands on its own, without a price high."))
    elif pos > 2 / 3:
        a7 = (hi_txt + f". PE {pe_txt} is inside the rational range but in its top third "
              f"(SELL {cur.sell_pe:g}x): a review, not an automatic sell.")
    else:
        a7 = (hi_txt + f". PE {pe_txt} sits {'below BUY' if pos < 0 else 'in the lower two-thirds of the wedge'}: "
              + ("the 52-week high is a price event, not a valuation sell." if near_high else "no sell signal."))
    out.append(("Is a SELL signal genuine valuation stretch, or merely a 52-week high?", a7))
    return out


def _headline(inputs: WedgeInputs, cur: WedgePoint | None) -> str:
    t = inputs.ticker.split(".")[0]
    if cur is None or cur.position is None:
        return f"{t}: no wedge (EPS or multiples missing)"
    fair = (f" / fair {_money(cur.fair_value)} ({cur.fair_pe:.1f}x)" if cur.fair_value else "")
    basis = " on smoothed EPS" if inputs.smoothing else ""
    return (f"{t} {_money(cur.price)}: {cur.zone} ({cur.position:.0%} BUY->SELL). "
            f"PE {cur.actual_pe:.0f}x{basis} vs BUY {cur.buy_pe:g}x / SELL {cur.sell_pe:g}x. "
            f"BUY {_money(cur.buy_value)}{fair} / SELL {_money(cur.sell_value)}.")


# ── Loading inputs from the repo ────────────────────────────────────────────

class WedgeConfigMissing(FileNotFoundError):
    pass


def _to_date(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def ticker_slug(ticker: str) -> str:
    return ticker.lower().replace(".", "_")


def normalise_ticker(raw: str, default_suffix: str = ".AX") -> str:
    t = raw.strip().upper()
    if t.startswith("ASX:"):
        t = t[4:]
    return t if "." in t else f"{t}{default_suffix}"


def earnings_from_config(cfg: dict, source_label: str) -> list[EarningsPoint]:
    out = []
    for row in cfg.get("earnings") or []:
        if row.get("ttm_eps") is None:
            continue
        out.append(EarningsPoint(
            date=_to_date(row["date"]),
            period=str(row.get("period", "")),
            eps_cents=float(row["ttm_eps"]),
            norm_eps_cents=float(row["norm_eps"]) if row.get("norm_eps") is not None else None,
            source=str(row.get("source") or cfg.get("eps_source") or source_label),
            notes=str(row.get("notes") or ""),
        ))
    for row in cfg.get("extra_eps") or []:
        # Hand-entered reported figures (e.g. from the company's own results
        # release) for periods the SWS export does not cover. Source required.
        if row.get("eps") is None or not row.get("source"):
            continue
        out.append(EarningsPoint(
            date=_to_date(row["date"]), period=str(row["period"]), eps_cents=float(row["eps"]),
            source=str(row["source"]), notes=str(row.get("notes") or "Reported (company release)"),
        ))
    excluded = {str(x.get("period")).upper() for x in cfg.get("eps_exclude") or [] if isinstance(x, dict)}
    out = [e for e in out if e.period.upper() not in excluded]
    ttm, _missing = half_year_ttm(cfg, [e for e in out if e.period.upper().startswith("FY")])
    return sorted(out + ttm, key=lambda e: e.date)


def smooth_eps(earnings: list[EarningsPoint], years: float = 5,
               exclude: Iterable[str] = ()) -> list[EarningsPoint]:
    """Through-the-cycle EPS for a cyclical, with no look-ahead.

    At each release, the smoothed EPS is the plain average of every reported
    12-month EPS figure released in the previous ``years`` years, this one
    included, as known on that day. Periods in ``exclude`` (a one-off like
    BHP's FY16 Samarco loss) are left out of every average but keep their own
    release date, so the corridor still steps there. The result is stored as
    ``norm_eps_cents`` and held flat until the next release.
    """
    skip = {str(x).upper() for x in exclude}
    ordered = sorted(earnings, key=lambda e: e.date)
    window = dt.timedelta(days=round(365.25 * years))
    for e in ordered:
        used = [x for x in ordered
                if e.date - window < x.date <= e.date and x.period.upper() not in skip]
        if used:
            e.norm_eps_cents = round(sum(x.eps_cents for x in used) / len(used), 3)
            e.notes = (e.notes + f" | smoothed {e.norm_eps_cents:.1f}c = average of "
                       f"{len(used)} figures released since {(e.date - window):%b %Y}").strip(" |")
        else:
            e.norm_eps_cents = None
    return ordered


def eps_coverage_gaps(earnings: list[EarningsPoint]) -> dict[str, list[str]]:
    """Which six-monthly EPS updates are absent between the first and last one.

    ASX companies report twice a year: a half-year (1H, trailing 12 months at
    that point) and a full year (FY). Returns {'1H': [...], 'FY': [...]}.
    """
    have = set()
    for e in earnings:
        m = re.match(r"^(FY|1H)\s*(\d{4})", e.period.strip().upper())
        if m:
            have.add((int(m.group(2)), 0 if m.group(1) == "1H" else 1))
    if not have:
        return {"1H": [], "FY": []}
    lo, hi = min(have), max(have)
    gaps = {"1H": [], "FY": []}
    y, h = lo
    while (y, h) <= hi:
        if (y, h) not in have:
            gaps["1H" if h == 0 else "FY"].append(f"{'1H' if h == 0 else 'FY'}{y}")
        y, h = (y, 1) if h == 0 else (y + 1, 0)
    return gaps


def _fy_year(period: str) -> int | None:
    m = re.match(r"^(?:FY|1H|H1)\s*(\d{4})$", period.strip().upper())
    return int(m.group(1)) if m else None


def half_year_ttm(cfg: dict, annual: list[EarningsPoint]) -> tuple[list[EarningsPoint], list[str]]:
    """Trailing-12-month EPS at each half-year release, from reported halves only.

    TTM at 1H{Y} = FY{Y-1} EPS - 1H{Y-1} EPS + 1H{Y} EPS. A point is made only
    when all three are reported. Returns (points, missing half labels) so the
    gaps can be shown rather than filled.
    """
    fy = {_fy_year(e.period): e for e in annual if e.period.upper().startswith("FY")}
    halves = {}
    for h in cfg.get("half_year_eps") or []:
        y = _fy_year(str(h.get("period", "")))
        if y is not None and h.get("eps") is not None:
            halves[y] = h
    points: list[EarningsPoint] = []
    for y, h in sorted(halves.items()):
        prior, last_fy = halves.get(y - 1), fy.get(y - 1)
        if prior is None or last_fy is None or not h.get("release"):
            continue
        ttm = round(last_fy.eps_cents - float(prior["eps"]) + float(h["eps"]), 3)
        points.append(EarningsPoint(
            date=_to_date(h["release"]), period=f"1H{y} TTM", eps_cents=ttm,
            source=str(h.get("source") or ""),
            notes=(f"Computed TTM from reported halves: FY{y - 1} {last_fy.eps_cents:g}c "
                   f"- 1H{y - 1} {float(prior['eps']):g}c + 1H{y} {float(h['eps']):g}c"),
        ))
    # Every half from the first FY's own 1H (needed for the first TTM) to the
    # latest half that has had time to be reported (1H results are due by end Feb).
    years = sorted(y for y in fy if y is not None)
    missing: list[str] = []
    if years:
        last = years[-1] + 1 if dt.date.today() >= dt.date(years[-1] + 1, 3, 1) else years[-1]
        missing = [f"1H{y}" for y in range(years[0], last + 1) if y not in halves]
    return points, missing


def multiples_from_config(cfg: dict) -> list[MultipleRegime]:
    hist = cfg.get("multiple_history") or []
    regimes = [
        MultipleRegime(_to_date(h["date"]), float(h["buy_pe"]), float(h["sell_pe"]),
                       str(h.get("reason") or ""), "config multiple_history")
        for h in hist
    ]
    return sorted(regimes, key=lambda m: m.date)


def multiples_from_git(path: Path, repo: Path, start: dt.date) -> list[MultipleRegime]:
    """Every change to buy_multiple/sell_multiple in the config's git history,
    dated by commit. Empty if git is unavailable or the history is shallow."""
    try:
        rel = path.resolve().relative_to(repo.resolve()).as_posix()
        log = subprocess.run(
            ["git", "-C", str(repo), "log", "--reverse", "--format=%H %as", "--", rel],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.split("\n")
    except Exception:
        return []
    regimes: list[MultipleRegime] = []
    for line in filter(None, log):
        sha, day = line.split()
        try:
            blob = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{rel}"],
                                  capture_output=True, text=True, timeout=30, check=True).stdout
            c = yaml.safe_load(blob) or {}
            buy, sell = float(c["buy_multiple"]), float(c["sell_multiple"])
        except Exception:
            continue
        if regimes and (regimes[-1].buy_pe, regimes[-1].sell_pe) == (buy, sell):
            continue
        if not regimes:
            regimes.append(MultipleRegime(start, buy, sell,
                                          "First recorded framework, applied to the full history", "git"))
        else:
            regimes.append(MultipleRegime(_to_date(day), buy, sell,
                                          f"valuation config changed (commit {sha[:7]})", "git"))
    return regimes


def thesis_notes(theses_dir: Path, ticker: str) -> list[Note]:
    path = theses_dir / f"{ticker.split('.')[0].upper()}.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---", 2)[1]) or {}
    except Exception:
        return []
    notes = []
    for r in fm.get("reviews") or []:
        if not isinstance(r, dict) or not r.get("date"):
            continue
        what = r.get("verdict") or r.get("trigger") or r.get("summary") or "review"
        try:
            notes.append(Note(_to_date(r["date"]), f"Thesis updated: {what}", "thesis"))
        except Exception:
            continue
    return notes


def fetch_daily_prices(exchange_ticker: str, start: str) -> pd.Series:
    """Every raw daily close from EODHD since *start* (empty if EODHD has none)."""
    from .pathing import ensure_repo_root_on_path
    ensure_repo_root_on_path()
    from shared import eodhd
    try:
        return eodhd.close_series(eodhd.symbol(exchange_ticker), start)
    except eodhd.EODHDError as e:
        print(f"[sally] {exchange_ticker}: no daily prices from EODHD ({e})", flush=True)
        return pd.Series(dtype=float)


_TRADING_CCY = {"AX": "AUD", "L": "GBP", "T": "JPY", "HK": "HKD", "SI": "SGD", "TO": "CAD"}


def trading_currency(exchange_ticker: str) -> str:
    return _TRADING_CCY.get(exchange_ticker.rsplit(".", 1)[1].upper(), "USD") if "." in exchange_ticker else "USD"


def fetch_fx(eps_ccy: str, trade_ccy: str, start: str) -> pd.Series:
    """Daily trade-currency units per one EPS-currency unit (EODHD, e.g. USDAUD.FOREX)."""
    from .pathing import ensure_repo_root_on_path
    ensure_repo_root_on_path()
    from shared import eodhd
    try:
        return eodhd.fx_series(eps_ccy, trade_ccy, start)
    except eodhd.EODHDError as e:
        print(f"[sally] no {eps_ccy}{trade_ccy} FX from EODHD ({e})", flush=True)
        return pd.Series(dtype=float)


def decision_notes(repo: Path, ticker: str) -> list[Note]:
    """Buy (and sell) dates for this ticker from the IRR ledger, data/decisions.json.

    Dates only: the ledger is public and the chart is emailed, so no amounts.
    """
    import json
    path = repo / "data" / "decisions.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("decisions") or []
    except Exception:
        return []
    base = ticker.split(".")[0].upper()
    mine = sorted((r for r in rows if str(r.get("ticker", "")).upper() == base and r.get("date")),
                  key=lambda r: r["date"])
    notes = []
    sells: dict[dt.date, list[int]] = {}
    for i, r in enumerate(mine, 1):
        notes.append(Note(_to_date(r["date"]), f"Bought (decision {i} of {len(mine)})", "decision"))
        sold = r.get("sell_date") or r.get("exit_date")
        if not sold and str(r.get("status", "")).upper() == "CLOSED" and r.get("flows"):
            sold = max(f[0] for f in r["flows"])        # a closed decision's last cash flow is the sale
        if sold:
            sells.setdefault(_to_date(sold), []).append(i)
    for d, idx in sorted(sells.items()):
        which = f"decision {idx[0]}" if len(idx) == 1 else "decisions " + ", ".join(map(str, idx))
        notes.append(Note(d, f"Sold ({which})", "decision"))
    return sorted(notes, key=lambda n: n.date)


def resolve_start(start: str | None, decisions: list[Note]) -> dt.date | None:
    """'full'/None -> whole history; 'year_before_buy' -> 365 days before the
    first buy in the ledger; 'YYYY-MM-DD' -> that date."""
    if not start or str(start).strip().lower() in ("", "full", "all"):
        return None
    s = str(start).strip().lower()
    if s in ("year_before_buy", "year-before-buy"):
        buys = [n.date for n in decisions if n.label.startswith("Bought")]
        return (min(buys) - dt.timedelta(days=365)) if buys else None
    return _to_date(s)


def _apply_archetype(cfg: dict, exch: str, fname: str, classification=None) -> str:
    """``buy_multiple: archetype`` in a valuation YAML: the BUY multiple (and
    its EPS basis) come from config/valuation_archetypes.yaml through
    shared/classifier.py, the single source of truth for buy multiples. Writes
    the number into ``cfg`` (and any ``buy_pe: archetype`` history row) and
    returns the note printed on the chart. A YAML with a number keeps it."""
    if str(cfg.get("buy_multiple", "")).strip().lower() != "archetype":
        return ""
    from shared import classifier
    cls = classification
    if cls is None:
        cls = classifier.classification_for(exch)
    if cls.buy_multiple is None:
        from shared import classifier as _c
        label = _c.archetype_label(_c.load_rules(), cls.archetype)
        raise WedgeConfigMissing(
            f"no wedge for {exch}: {label} archetype has no P/E line ({cls.error or cls.alt_metric or 'pre-profit'})"
            + (" - suggested by the classifier, not confirmed; set the archetype in config/ticker_archetypes.yaml "
               "if it is valued on earnings" if getattr(cls, "suggested", False) else "") + ".")
    bm = float(cls.buy_multiple)
    cfg["buy_multiple"] = bm
    cfg["_cls_used"] = cls
    for row in cfg.get("multiple_history") or []:
        if str(row.get("buy_pe", "")).strip().lower() == "archetype":
            row["buy_pe"] = bm
    basis = str(cls.eps_basis or "ttm")
    if basis.startswith("avg_") and not cfg.get("eps_smoothing"):
        cfg["_annual_basis"] = True            # an N-year average of annual EPS: halves are not gaps
        cfg["eps_smoothing"] = {"years": int(basis[4:].rstrip("y")),
                                "reason": f"the {cls.archetype} archetype values on {basis.replace('_', ' ')} EPS"}
    rules = classifier.load_rules()
    mods = "".join(f" {m.delta:+g} {m.name}" for m in cls.modifiers)
    return (f"BUY {bm:g}x from the archetype rules: {classifier.archetype_label(rules, cls.archetype)} "
            + (f"{cls.base_multiple:g}x" if cls.base_multiple is not None else "") + f"{mods}" + (f", {'; '.join(cls.guardrails)}" if cls.guardrails else "")
            + f", on {classifier.eps_basis_label(rules, basis)}"
            + (" (suggested by the classifier, not yet confirmed in config/ticker_archetypes.yaml)"
               if cls.suggested else " (confirmed)") + ".")


def auto_sell_multiple(cls) -> tuple[float, str]:
    from shared import classifier
    return classifier.sell_multiple_for(cls)


def auto_config(exch: str, *, fund: dict | None = None, classification=None,
                trend_rows: list[dict] | None = None, today: dt.date | None = None) -> dict:
    """A valuation config built from EODHD for a holding with no
    valuations/<slug>.yaml: statutory annual EPS (``eodhd.annual_eps``: NPAT /
    checked share count, each from its release date), the archetype BUY
    multiple, the SELL rule above and the analyst consensus as a forecast.
    Raises WedgeConfigMissing for a company with no P/E-based value
    (pre-profit, loss-making, or an archetype valued on another metric)."""
    from shared import classifier, eodhd
    today = today or dt.date.today()
    sym = eodhd.symbol(exch)
    fund = fund if fund is not None else eodhd.fundamentals(sym)
    cls = classification if classification is not None else classifier.classification_for(exch)
    rules = classifier.load_rules()
    label = classifier.archetype_label(rules, cls.archetype)
    if cls.buy_multiple is None:
        raise WedgeConfigMissing(
            f"no wedge for {exch}: {label} archetype has no P/E line ({cls.alt_metric or 'pre-profit'})"
            + (" - suggested by the classifier, not confirmed; set the archetype in config/ticker_archetypes.yaml "
               "if it is valued on earnings" if getattr(cls, "suggested", False) else "") + ".")
    from shared.eps_history import eodhd_earnings_rows
    earnings, ccy = eodhd_earnings_rows(exch, fund=fund, today=today, divs={})
    if not earnings:
        raise WedgeConfigMissing(f"no wedge for {exch}: EODHD has no usable annual EPS.")
    last = earnings[-1]
    if last["ttm_eps"] <= 0:
        raise WedgeConfigMissing(f"no wedge for {exch}: loss-making ({last['period']} statutory EPS "
                                 f"{last['ttm_eps']:.1f}c), so no P/E-based value.")
    sell, sell_why = auto_sell_multiple(cls)
    cfg = {
        "_auto": True,
        "_annual_basis": True,           # annual statements: missing halves are not gaps
        "_classification": cls,
        "_auto_note": (f"Automatic config (no valuations/ file): statutory annual EPS from EODHD; "
                       f"BUY {cls.buy_multiple:g}x from the {label} archetype; SELL {sell:g}x = {sell_why}."),
        "ticker": exch,
        "company_name": (fund.get("General") or {}).get("Name") or exch,
        "buy_multiple": "archetype",
        "sell_multiple": sell,
        "multiple_history": [{"date": earnings[0]["date"], "buy_pe": "archetype", "sell_pe": sell,
                              "reason": "automatic config (archetype BUY, SELL rule)"}],
        "fair_split": 0.3,
        "eps_basis": "reported_ttm",
        "earnings": earnings,
        "price_data": {"start_date": (today - dt.timedelta(days=round(365.25 * 11))).isoformat()},
    }
    if ccy and ccy != trading_currency(exch) and not (ccy == "GBP" and exch.upper().endswith(".L")):
        cfg["eps_currency"] = ccy
    cfg["_consensus"] = _consensus_case(sym, last["period_end"], ccy, ccy, trend_rows)
    return cfg


def _consensus_case(sym: str, last_fy_end: str, cons_ccy: str, eps_ccy: str,
                    trend_rows: list[dict] | None = None) -> dict | None:
    """Analyst consensus (EODHD earnings trends) as a forecast case, in the
    config's EPS currency (converted once at today's rate when it differs).
    None when there is no usable estimate."""
    from shared import eodhd
    try:
        cons = eodhd.consensus_eps(sym, last_fy_end, trend_rows)
    except eodhd.EODHDError as exc:
        print(f"[wedge] {sym}: no consensus ({exc})")
        return None
    if not cons:
        return None
    rate, note = 1.0, ""
    if cons_ccy and eps_ccy and cons_ccy != eps_ccy:
        try:
            rate, day = eodhd.fx_rate(cons_ccy, eps_ccy)
            note = f" Converted from {cons_ccy} at {rate:.4f} ({day})."
        except eodhd.EODHDError as exc:
            print(f"[wedge] {sym}: consensus in {cons_ccy}, no FX to {eps_ccy} ({exc})")
            return None
    rows = []
    for c in cons[:2]:
        end = dt.date.fromisoformat(c["period_end"])
        rng = (f", range {c['low'] * 100 * rate:.1f}-{c['high'] * 100 * rate:.1f}c"
               if c.get("low") is not None and c.get("high") is not None else "")
        rows.append({"period": f"FY{end.year}", "release": (end + dt.timedelta(days=61)).isoformat(),
                     "eps": round(c["eps"] * 100 * rate, 3),
                     "note": f"consensus, {c['analysts']} analysts{rng}"})
    n = max(c["analysts"] for c in cons[:2])
    return {"label": "Consensus", "rows": rows,
            "basis": (f"Analyst consensus EPS from EODHD earnings trends ({n} analysts), "
                      f"released ~2 months after each year end." + note)}


def _yaml_consensus(cfg: dict, exch: str, eps_ccy: str) -> dict | None:
    """Consensus forecast for a hand-made valuation YAML with no forecast block,
    in the YAML's own EPS currency (``eps_currency`` or the trading currency).
    Best effort: no EODHD, no consensus, no forecast."""
    try:
        from shared import eodhd
        sym = eodhd.symbol(exch)
        fys = [r for r in cfg.get("earnings") or [] if str(r.get("period", "")).upper().startswith("FY")
               and r.get("period_end")]
        if not fys:
            return None
        last_end = max(str(r["period_end"]) for r in fys)
        ann = eodhd.annual_eps(sym)
        cons_ccy = str((ann[-1].get("currency") if ann else "") or "").upper()
        target = (eps_ccy or trading_currency(exch)).upper()
        return _consensus_case(sym, last_end, cons_ccy or target, target)
    except Exception as exc:
        print(f"[wedge] {exch}: consensus forecast skipped ({type(exc).__name__}: {exc})")
        return None


def load_wedge_inputs(ticker: str, *, repo: Path, prices: pd.Series | None = None,
                      company_name: str | None = None, fx: pd.Series | None = None,
                      start: str | None = None, classification=None, auto: bool | None = None,
                      fund: dict | None = None, trend_rows: list[dict] | None = None) -> WedgeInputs:
    exch = normalise_ticker(ticker)
    path = repo / "valuations" / f"{ticker_slug(exch)}.yaml"
    if path.exists():
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        if auto is False:
            raise WedgeConfigMissing(f"No valuations/{path.name} and automatic configs are off.")
        try:
            cfg = auto_config(exch, classification=classification, fund=fund, trend_rows=trend_rows)
        except WedgeConfigMissing:
            raise
        except Exception as exc:
            raise WedgeConfigMissing(f"No valuations/{path.name}, and no automatic config from EODHD "
                                     f"({type(exc).__name__}: {exc}).") from None
        classification = cfg.pop("_classification", classification)
    warnings: list[str] = []
    if cfg.get("_auto_note"):
        warnings.append(cfg["_auto_note"])
    if str(cfg.get("earnings_source", "")).strip().lower() == "eodhd":
        # Hand-set framework, EPS from EODHD's reported statements (the
        # earnings: rows in the file, if any, are ignored).
        from shared.eps_history import eodhd_earnings_rows
        try:
            rows, ccy = eodhd_earnings_rows(exch, fund=fund, divs={})
        except Exception as exc:
            raise WedgeConfigMissing(f"valuations/{path.name}: earnings_source eodhd, but EODHD gave no EPS "
                                     f"({type(exc).__name__}: {exc}).") from None
        if not rows:
            raise WedgeConfigMissing(f"valuations/{path.name}: earnings_source eodhd, but EODHD has no annual EPS.")
        cfg["earnings"] = rows
        cfg["_annual_basis"] = True
        if ccy and ccy != trading_currency(exch) and not cfg.get("eps_currency"):
            cfg["eps_currency"] = ccy
        warnings.append("EPS: statutory annual figures from EODHD statements (earnings_source: eodhd).")
    multiple_note = _apply_archetype(cfg, exch, path.name, classification)
    if multiple_note:
        warnings.append(multiple_note)
    if str(cfg.get("sell_multiple", "")).strip().lower() == "auto":
        cls_ = cfg.get("_cls_used")
        if cls_ is None:
            from shared import classifier
            cls_ = classifier.classification_for(exch)
        sm, why = auto_sell_multiple(cls_)
        cfg["sell_multiple"] = sm
        for row in cfg.get("multiple_history") or []:
            if str(row.get("sell_pe", "")).strip().lower() == "auto":
                row["sell_pe"] = sm
        warnings.append(f"SELL {sm:g}x = {why} (sell rule in config/valuation_archetypes.yaml).")

    earnings = earnings_from_config(cfg, f"valuations/{path.name}")
    if not earnings:
        raise WedgeConfigMissing(f"valuations/{path.name} has no earnings history.")
    n_est = sum(1 for e in earnings if e.notes.strip().lower().startswith("est"))
    n_der = sum(1 for e in earnings if e.notes.strip().lower().startswith("derived"))
    if n_est:
        warnings.append(f"{n_est} of {len(earnings)} EPS points are unverified estimates (notes 'Est.').")
    if n_der:
        warnings.append(f"{n_der} of {len(earnings)} EPS points are derived from reported NPAT/growth; "
                        "method in valuations/" + path.name + ".")
    annual_only = [e for e in earnings if e.period.upper().startswith("FY")]
    ttm_points, missing_halves = half_year_ttm(cfg, annual_only)
    for x in cfg.get("eps_exclude") or []:
        if isinstance(x, dict) and x.get("period"):
            warnings.append(f"{x['period']} EPS left out: {x.get('reason', 'basis differs')}.")
    if missing_halves and cfg.get("half_year_eps"):
        have = [p.period.replace(" TTM", "") for p in ttm_points]
        warnings.append(
            "Half-year EPS missing for " + _ranges(missing_halves)
            + ": EPS steps only at full-year results there"
            + (f" (half-year TTM update available for {', '.join(have)})" if have else "")
            + ". Add each half from its ASX Appendix 4D to half_year_eps."
        )

    start_ = start_eps = earnings[0].date
    multiples = multiples_from_config(cfg)
    source = "config multiple_history"
    if not multiples and path.exists():
        multiples = multiples_from_git(path, repo, start_eps)
        source = "git history of the valuation config"
        if len(multiples) <= 1:
            multiples, source = [], "config"
    if not multiples:
        if cfg.get("buy_multiple") is None or cfg.get("sell_multiple") is None:
            raise WedgeConfigMissing(f"valuations/{path.name} needs buy_multiple and sell_multiple.")
        multiples = [MultipleRegime(start_eps, float(cfg["buy_multiple"]), float(cfg["sell_multiple"]),
                                    "Valuation config (never changed)", "config")]

    notes = [Note(_to_date(a["date"]), str(a["label"]), str(a.get("kind", "note")))
             for a in (cfg.get("annotations") or []) if a.get("date") and a.get("label")]
    notes += thesis_notes(repo / "theses", exch)
    decisions = decision_notes(repo, exch)
    notes += decisions
    show_from = resolve_start(start, decisions)
    # Only gaps inside what the chart shows (earlier figures just feed smoothing).
    shown_from = show_from or (earnings[0].date if earnings else None)
    in_force = max((e.date for e in earnings if shown_from and e.date <= shown_from), default=None)
    gaps = eps_coverage_gaps([e for e in earnings if in_force is None or e.date >= in_force])
    if shown_from:   # a half or year whose result would have come out before the chart starts is not a gap
        gaps["1H"] = [g for g in gaps["1H"] if dt.date(int(g[2:]), 3, 1) >= shown_from]
        gaps["FY"] = [g for g in gaps["FY"] if dt.date(int(g[2:]), 9, 1) >= shown_from]
    gap_txt = []
    if gaps["FY"]:
        gap_txt.append("full-year " + _ranges(gaps["FY"]))
    if gaps["1H"] and not cfg.get("half_year_eps") and not cfg.get("_annual_basis"):
        gap_txt.append("half-year " + _ranges(gaps["1H"]))
    if gap_txt:
        warnings.append("No EPS in the data for " + "; ".join(gap_txt)
                        + ": the corridor holds the previous figure through each gap.")

    cfg_start = str((cfg.get("price_data") or {}).get("start_date") or start_.isoformat())
    # Fetch a year before the first date shown so 52-week highs are real there.
    fetch_from = min(_to_date(cfg_start), show_from - dt.timedelta(days=400)) if show_from else _to_date(cfg_start)
    if prices is None:
        prices = fetch_daily_prices(exch, fetch_from.isoformat())

    eps_ccy = str(cfg.get("eps_currency") or "").upper()
    trade_ccy = trading_currency(exch)
    fx_label = ""
    if eps_ccy and eps_ccy != trade_ccy:
        if fx is None:
            fx = fetch_fx(eps_ccy, trade_ccy, fetch_from.isoformat())
        fx_label = f"{trade_ccy} per {eps_ccy}, EODHD {eps_ccy}{trade_ccy}.FOREX, at each release date"
        warnings.append(f"EPS is reported in {eps_ccy} cents and converted to {trade_ccy} once, at the exchange "
                        f"rate on the day each result was released (EODHD {eps_ccy}{trade_ccy}.FOREX), so BUY and SELL stay "
                        "flat until the next result.")
    else:
        eps_ccy, fx = "", None

    smoothing = ""
    sm = cfg.get("eps_smoothing") or {}
    if sm:
        yrs = float(sm.get("years", 5))
        excl = [str(x) for x in sm.get("exclude") or []]
        earnings = smooth_eps(earnings, yrs, excl)
        smoothing = (f"Smoothed EPS: average of the reported 12-month EPS figures released in the previous "
                     f"{yrs:g} years, as known at each release"
                     + (f"; {', '.join(excl)} left out as a one-off" if excl else ""))
        if sm.get("reason"):
            warnings.append(f"EPS is smoothed through the cycle: {sm['reason']}")
    depressed = []
    for dpe in cfg.get("depressed_earnings") or []:
        if not dpe.get("start"):
            continue
        ref_period = str(dpe.get("reference_period") or "").upper()
        ref = next((x for x in earnings if x.period.upper() == ref_period), None)
        item = {"start": _to_date(dpe["start"]),
                "end": _to_date(dpe["end"]) if dpe.get("end") else None,
                "label": str(dpe.get("label") or "Statutory EPS understates earning power"),
                "reference_period": ref_period if ref else None,
                "reference_eps": ref.eps_cents if ref else None}
        depressed.append(item)
        cur_m = multiples[-1] if multiples else None
        txt = (f"{item['label']} ({item['start']:%b %Y} to "
               f"{item['end'].strftime('%b %Y') if item['end'] else 'now'}): the statutory corridor understates "
               "earning power there")
        if ref and cur_m and not eps_ccy:
            split = cfg.get("fair_split", 0.3)
            fair_pe = cur_m.buy_pe + (split or 0) * (cur_m.sell_pe - cur_m.buy_pe) if split is not None else None
            txt += (f". On {ref.period} EPS ({ref.eps_cents:.1f}c, the last normal year) the corridor would be "
                    f"BUY {_money(ref.eps_cents * cur_m.buy_pe / 100)}"
                    + (f" / fair {_money(ref.eps_cents * fair_pe / 100)}" if fair_pe else "")
                    + f" / SELL {_money(ref.eps_cents * cur_m.sell_pe / 100)}")
        warnings.append(txt + ".")
    period_notes = {str(k).upper(): str(v) for k, v in (cfg.get("period_notes") or {}).items()}
    fc = cfg.get("forecast") or {}
    if not fc and cfg.get("auto_forecast", True) is not False:
        case = cfg.get("_consensus") if "_consensus" in cfg else _yaml_consensus(cfg, exch, eps_ccy)
        if case:
            fc = {"cases": [case]}

    raw_cases = fc.get("cases") or ([{"label": fc.get("label") or "Forecast", "basis": fc.get("basis"),
                                      "rows": fc.get("rows")}] if fc.get("rows") else [])
    forecast: list[dict] = []
    forecast_cases: list[dict] = []
    for case in raw_cases:
        label = str(case.get("label") or "Forecast")
        rows = sorted(
            ({"case": label, "period": str(r["period"]).upper(), "date": _to_date(r["release"]),
              "eps_cents": float(r["eps"]), "note": str(r.get("note") or "")}
             for r in case.get("rows") or [] if r.get("period") and r.get("release") and r.get("eps") is not None),
            key=lambda r: r["date"])
        if not rows:
            continue
        if sm:
            # Same basis as the wedge: each forecast year joins the reported
            # years in the smoothing window, as it would have on release.
            fut = [EarningsPoint(r["date"], r["period"] + "F", r["eps_cents"]) for r in rows]
            hist = [EarningsPoint(e.date, e.period, e.eps_cents) for e in earnings]
            for pt in smooth_eps(hist + fut, float(sm.get("years", 5)), [str(x) for x in sm.get("exclude") or []]):
                for r in rows:
                    if pt.period == r["period"] + "F":
                        r["eps_basis_cents"] = pt.norm_eps_cents
        forecast += rows
        forecast_cases.append({"label": label, "basis": str(case.get("basis") or "").strip()})
        warnings.append(f"Right of today, {label}: "
                        + ", ".join(f"{r['period']}F EPS {r['eps_cents']:.1f}c" for r in rows)
                        + ". Not reported: an assumption, shown lighter and never used for the zones or alerts.")
    outlook = cfg.get("outlook") or {}
    fy_ends = [_to_date(r["period_end"]).month for r in cfg.get("earnings") or []
               if r.get("period_end") and str(r.get("period", "")).upper().startswith("FY")]
    fy_end_month = int(cfg.get("fy_end_month") or (max(set(fy_ends), key=fy_ends.count) if fy_ends else 6))
    return WedgeInputs(
        period_notes=period_notes,
        ticker=exch,
        company_name=company_name or str(cfg.get("company_name") or exch),
        currency=str(cfg.get("currency") or ("A" if exch.endswith(".AX") else "")),
        eps_basis=(smoothing or str(cfg.get("eps_basis") or "reported_ttm")),
        earnings=earnings,
        multiples=multiples,
        prices=prices,
        notes=sorted(notes, key=lambda n: n.date),
        multiples_source=source,
        warnings=warnings,
        eps_currency=eps_ccy,
        fx=fx,
        fx_label=fx_label,
        start=show_from,
        fy_end_month=fy_end_month,
        fair_split=(None if cfg.get("fair_split", 0.3) is None else float(cfg.get("fair_split", 0.3))),
        smoothing=smoothing,
        depressed=depressed,
        forecast=forecast,
        forecast_cases=forecast_cases,
        forecast_label=" vs ".join(c["label"] for c in forecast_cases),
        forecast_basis=" ".join(f"{c['label']}: {c['basis']}" if len(forecast_cases) > 1 else c["basis"]
                                for c in forecast_cases if c["basis"]),
        outlook=outlook,
        multiple_note=multiple_note,
        forecast_end=_to_date(fc["extend_to"]) if forecast and fc.get("extend_to") else None,
    )


def _ranges(labels: list[str]) -> str:
    """['1H2016','1H2017','1H2018','1H2025'] -> '1H2016-1H2018, 1H2025' (same for FY)."""
    prefix = labels[0][:2] if labels else "1H"
    ys = sorted(int(l[2:]) for l in labels)
    out, start = [], None
    for i, y in enumerate(ys):
        if start is None:
            start = y
        if i == len(ys) - 1 or ys[i + 1] != y + 1:
            out.append(f"{prefix}{start}" if start == y else f"{prefix}{start}-{prefix}{y}")
            start = None
    return ", ".join(out)


def write_outputs(result: WedgeResult, folder: Path) -> dict[str, Path]:
    """Per-point CSV (every field the corridor was built from) + summary JSON."""
    import json
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / "wedge_points.csv"
    json_path = folder / "wedge.json"
    result.points_frame().to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
    return {"csv": csv_path, "json": json_path}


def iter_tickers(raw: str) -> Iterable[str]:
    for tok in raw.replace(",", " ").split():
        if tok.strip():
            yield tok.strip().upper()
