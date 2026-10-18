# shared/eodhd.py
#
# The ONE source of market data for every agent: share prices, FX,
# dividends and company fundamentals all come from the paid EODHD
# subscription through this module. Nothing else in the repo may call
# Yahoo / yfinance, Alpha Vantage or FMP for numbers
# (tests/test_eodhd_only.py enforces that).
#
# Rules this module keeps, so the agents don't have to:
#
# * No fallback, no placeholder. If EODHD has no figure, callers get None
#   (or an EODHDError) and must show "n/a" with the reason. A missing number
#   is acceptable; a guessed one is not.
# * Every figure can say where it came from: ``SOURCE`` is the label agents
#   print next to a price or ratio, and ``eod()`` rows carry the trading date.
# * Endpoints, parameters and field names are exactly those documented in
#   .claude/skills/eodhd-api/references/endpoints/ (eod, real-time,
#   fundamentals, div). Read those before adding a call here.
#
# Plumbing only: stdlib HTTP (urllib), so Harry's and Theo's minimal
# workflow installs still import it. pandas is imported lazily inside the
# helpers that return frames.
#
# Symbols: EODHD uses CODE.EXCHANGE with its own exchange codes. ASX is
# ``.AU`` (not Yahoo's .AX), London is ``.LSE`` (quoted in pence, like
# Yahoo's .L), US is ``.US``. EODHD has no Singapore, NZX or Tokyo feed on
# this plan: those raise EODHDNotCovered rather than borrowing another
# source.

from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from shared.securities import ASX, LSE, SGX, US, parse_security

BASE_URL = "https://eodhd.com/api"
SOURCE = "EODHD"
TOKEN_ENV = ("EODHD_API_TOKEN", "EODHD_API_KEY")

# Security.exchange (shared/securities.py) -> EODHD exchange code.
# A raw Yahoo suffix that EODHD also lists maps to its EODHD code; anything
# absent here is not covered (see get_exchanges_list in the EODHD docs).
_EXCHANGE_CODE = {
    ASX: "AU", LSE: "LSE", US: "US",
    # Already-EODHD spellings, so "PWH.AU" round-trips.
    "AU": "AU", "LSE": "LSE",
    # Yahoo suffix -> EODHD code, for the odd non-core watchlist name.
    "TO": "TO", "V": "V", "NE": "NEO", "DE": "XETRA", "XETRA": "XETRA", "F": "F",
    "PA": "PA", "AS": "AS", "BR": "BR", "LS": "LS", "SW": "SW", "MC": "MC",
    "VI": "VI", "IR": "IR", "CO": "CO", "ST": "ST", "OL": "OL", "HE": "HE",
    "KS": "KO", "KQ": "KQ", "KL": "KLSE", "JK": "JK", "BK": "BK", "TW": "TW",
    "SA": "SA", "MX": "MX", "JO": "JSE", "SS": "SHG", "SZ": "SHE",
}

# What EODHD quotes each exchange in. LSE prices are pence (GBX), checked
# against RMV.LSE (close 450.3 on 2026-10-01, i.e. 450.3p).
QUOTE_CURRENCY = {"AU": "AUD", "LSE": "GBX", "US": "USD", "TO": "CAD", "V": "CAD"}


class EODHDError(RuntimeError):
    """EODHD could not supply the figure. The message is safe to show."""


class EODHDNotConfigured(EODHDError):
    """No API token in the environment."""


class EODHDNotCovered(EODHDError):
    """The security's exchange is not on EODHD (e.g. SGX)."""


def get_token(env: Optional[Mapping[str, str]] = None) -> str:
    e = os.environ if env is None else env
    for name in TOKEN_ENV:
        v = (e.get(name) or "").strip()
        if v:
            return v
    return ""


def is_configured() -> bool:
    return bool(get_token())


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

def symbol(raw: object, default_exchange: str = ASX) -> str:
    """Any ticker spelling the repo uses -> EODHD symbol.

    ``NHC`` / ``NHC.AX`` / ``ASX:NHC`` -> ``NHC.AU``; ``RR.`` / ``RR.L`` ->
    ``RR.LSE``; ``POOL`` (default_exchange=US) -> ``POOL.US``; ``BRK.B`` ->
    ``BRK-B.US``. Raises EODHDNotCovered for SGX and other exchanges EODHD
    does not list.
    """
    text = str(raw or "").strip().upper()
    if text.endswith(".FOREX"):
        return text
    sec = parse_security(text, default_exchange)
    if sec.exchange == SGX:
        raise EODHDNotCovered(f"{text}: SGX is not on the EODHD plan")
    code = _EXCHANGE_CODE.get(sec.exchange)
    if not code:
        raise EODHDNotCovered(f"{text}: exchange '{sec.exchange}' is not on the EODHD plan")
    local = sec.code.replace(".", "-") if code == "US" else sec.code
    return f"{local}.{code}"


def fx_symbol(from_ccy: str, to_ccy: str) -> str:
    return f"{from_ccy.upper()}{to_ccy.upper()}.FOREX"


def quote_currency(sym: str) -> Optional[str]:
    return QUOTE_CURRENCY.get(sym.rsplit(".", 1)[-1]) if "." in sym else None


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

_CACHE: dict[str, Any] = {}
stats = {"requests": 0, "cache_hits": 0}


def _redact(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text


def _get(path: str, params: Optional[dict] = None, *, retries: int = 3, timeout: float = 30.0) -> Any:
    token = get_token()
    if not token:
        raise EODHDNotConfigured("EODHD_API_TOKEN is not set; no market data fetched")
    q = {k: v for k, v in (params or {}).items() if v is not None}
    q["api_token"] = token
    q.setdefault("fmt", "json")
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(q)}"
    key = f"{path}?{urllib.parse.urlencode(sorted((k, v) for k, v in q.items() if k != 'api_token'))}"
    if key in _CACHE:
        stats["cache_hits"] += 1
        return _CACHE[key]

    last = ""
    for attempt in range(retries + 1):
        try:
            stats["requests"] += 1
            req = urllib.request.Request(url, headers={"User-Agent": "Reporting-Agent/eodhd"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body) if body.strip() else None
            if isinstance(data, dict) and data.get("error") and len(data) <= 3:
                raise EODHDError(f"EODHD {path}: {data.get('error')}")
            _CACHE[key] = data
            return data
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status == 404:
                raise EODHDError(f"EODHD {path}: not found (404)") from None
            if status in (402, 403):
                hint = "API limit used up" if status == 402 else "token rejected"
                raise EODHDError(f"EODHD {path}: HTTP {status} ({hint})") from None
            last = f"HTTP {status}"
            if status != 429 and status < 500:
                raise EODHDError(f"EODHD {path}: {last}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = _redact(f"{type(exc).__name__}: {exc}", token)
        except json.JSONDecodeError:
            raise EODHDError(f"EODHD {path}: response was not JSON") from None
        if attempt < retries:
            time.sleep(2 ** attempt)
    raise EODHDError(f"EODHD {path}: {last} after {retries + 1} attempts")


def clear_cache() -> None:
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Endpoints (one function per documented endpoint)
# ---------------------------------------------------------------------------

def _iso(d: object) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, (dt.date, dt.datetime)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


def eod(sym: str, start: object = None, end: object = None, period: str = "d") -> list[dict]:
    """/eod/{SYMBOL}: [{date, open, high, low, close, adjusted_close, volume}], oldest first.

    ``close`` is the raw traded price; ``adjusted_close`` is split- and
    dividend-adjusted. Zero-volume "flat candles" are dropped for equities,
    as the EODHD docs recommend (FX rows always carry volume 0, so kept).
    """
    rows = _get(f"/eod/{sym}", {"from": _iso(start), "to": _iso(end), "period": period, "order": "a"})
    if not isinstance(rows, list):
        raise EODHDError(f"EODHD /eod/{sym}: unexpected response")
    if not sym.endswith(".FOREX"):
        rows = [r for r in rows if (r.get("volume") or 0) > 0 or period != "d"]
    return [r for r in rows if r.get("close") is not None]


def real_time(sym: str) -> dict:
    """/real-time/{SYMBOL}: delayed live quote; ``close`` is the live price."""
    data = _get(f"/real-time/{sym}")
    if not isinstance(data, dict):
        raise EODHDError(f"EODHD /real-time/{sym}: unexpected response")
    return data


def fundamentals(sym: str) -> dict:
    """/fundamentals/{SYMBOL}: the full company record (10 API calls, cached per run)."""
    data = _get(f"/fundamentals/{sym}")
    if not isinstance(data, dict) or not data.get("General"):
        raise EODHDError(f"EODHD /fundamentals/{sym}: no fundamentals")
    return data


def dividends(sym: str, start: object = None, end: object = None) -> list[dict]:
    """/div/{SYMBOL}: [{date (ex-date), value, unadjustedValue, currency, period, ...}]."""
    rows = _get(f"/div/{sym}", {"from": _iso(start), "to": _iso(end)})
    return rows if isinstance(rows, list) else []


# ---------------------------------------------------------------------------
# Derived helpers. Arithmetic on EODHD figures only, never an estimate.
# ---------------------------------------------------------------------------

def _num(v: object) -> Optional[float]:
    try:
        f = float(v)  # EODHD sends some numbers as strings ("21752000.00")
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


@dataclass
class PriceSummary:
    symbol: str
    last: float
    last_date: str
    prev: Optional[float]
    high_52w: float
    low_52w: float
    currency: Optional[str]
    source: str = SOURCE

    @property
    def label(self) -> str:
        return f"{SOURCE} close {self.last_date}"


def price_summary(sym: str, today: Optional[dt.date] = None) -> PriceSummary:
    """Last close, previous close and the 52-week high/low of raw closes."""
    today = today or dt.date.today()
    rows = eod(sym, today - dt.timedelta(days=372), today)
    closes = [(r["date"], float(r["close"])) for r in rows]
    if not closes:
        raise EODHDError(f"EODHD /eod/{sym}: no prices in the last year")
    cutoff = (today - dt.timedelta(days=365)).isoformat()
    year = [c for d, c in closes if d >= cutoff] or [closes[-1][1]]
    return PriceSummary(
        symbol=sym, last=closes[-1][1], last_date=closes[-1][0],
        prev=closes[-2][1] if len(closes) > 1 else None,
        high_52w=max(year), low_52w=min(year), currency=quote_currency(sym),
    )


def close_series(sym: str, start: object = None, end: object = None, *,
                 adjusted: bool = False, period: str = "d"):
    """pandas Series of closes on a tz-naive DatetimeIndex (empty if none)."""
    import pandas as pd

    rows = eod(sym, start, end, period)
    col = "adjusted_close" if adjusted else "close"
    s = pd.Series([float(r[col]) for r in rows if r.get(col) is not None],
                  index=pd.to_datetime([r["date"] for r in rows if r.get(col) is not None]),
                  dtype=float, name="Close")
    return s.sort_index()


def ohlcv_frame(sym: str, start: object = None, end: object = None):
    """DataFrame with Open/High/Low/Close/Volume (raw prices), DatetimeIndex."""
    import pandas as pd

    rows = eod(sym, start, end)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df.index = pd.to_datetime(df.pop("date"))
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()


def fx_series(from_ccy: str, to_ccy: str, start: object = None, end: object = None):
    """Daily *to_ccy* per one *from_ccy* (e.g. USD->AUD from USDAUD.FOREX)."""
    return close_series(fx_symbol(from_ccy, to_ccy), start, end)


def fx_rate(from_ccy: str, to_ccy: str) -> tuple[float, str]:
    """Latest daily FX close and its date."""
    if from_ccy.upper() == to_ccy.upper():
        return 1.0, dt.date.today().isoformat()
    rows = eod(fx_symbol(from_ccy, to_ccy), dt.date.today() - dt.timedelta(days=10))
    if not rows:
        raise EODHDError(f"EODHD: no FX rate for {from_ccy}{to_ccy}")
    return float(rows[-1]["close"]), rows[-1]["date"]


@dataclass
class Snapshot:
    """Current valuation figures straight from EODHD fundamentals.

    Ratios are plain multiples; yields are decimals (0.04 = 4%). Any field
    EODHD does not carry is None, never estimated.
    """
    symbol: str
    name: Optional[str] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ev: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    price_to_sales: Optional[float] = None
    dividend_yield: Optional[float] = None
    fcf_yield: Optional[float] = None
    trailing_eps: Optional[float] = None
    updated_at: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    source: str = SOURCE


def _latest_yearly(section: dict) -> Optional[dict]:
    yearly = (section or {}).get("yearly") or {}
    if not yearly:
        return None
    return yearly[max(yearly)]


def snapshot(sym: str, fund: Optional[dict] = None) -> Snapshot:
    f = fund if fund is not None else fundamentals(sym)
    g, h = f.get("General") or {}, f.get("Highlights") or {}
    v, s = f.get("Valuation") or {}, f.get("SharesStats") or {}
    snap = Snapshot(
        symbol=sym, name=g.get("Name"), currency=g.get("CurrencyCode"),
        market_cap=_num(h.get("MarketCapitalization")),
        shares_outstanding=_num(s.get("SharesOutstanding")),
        trailing_pe=_num(v.get("TrailingPE")), forward_pe=_num(v.get("ForwardPE")),
        ev=_num(v.get("EnterpriseValue")), ev_to_ebitda=_num(v.get("EnterpriseValueEbitda")),
        price_to_sales=_num(v.get("PriceSalesTTM")),
        dividend_yield=_num(h.get("DividendYield")),
        trailing_eps=_num(h.get("DilutedEpsTTM")) or _num(h.get("EarningsShare")),
        updated_at=g.get("UpdatedAt"),
    )
    cf = _latest_yearly((f.get("Financials") or {}).get("Cash_Flow") or {})
    fcf = _num((cf or {}).get("freeCashFlow"))
    if fcf is not None and snap.market_cap:
        snap.fcf_yield = fcf / snap.market_cap
        snap.notes.append(f"FCF yield = FY{str(cf.get('date'))[:4]} free cash flow / market cap")
    return snap


# Two EODHD share counts that disagree by more than this are not trusted.
SHARE_COUNT_TOLERANCE = 0.20
# A year-on-year change in shares on issue bigger than this needs both EODHD
# share sources to confirm it (a real rights issue does; a data glitch doesn't).
SHARE_JUMP_LIMIT = 0.50


def _outstanding_shares_at(f: dict, date: str) -> Optional[float]:
    """EODHD outstandingShares at a balance date (within ~6 months before it)."""
    q = ((f.get("outstandingShares") or {}).get("quarterly") or {}).values()
    dated = sorted((r.get("dateFormatted") or "", _num(r.get("shares"))) for r in q
                   if (r.get("dateFormatted") or "") <= date and _num(r.get("shares")))
    if dated:
        gap = (dt.date.fromisoformat(date[:10]) - dt.date.fromisoformat(dated[-1][0][:10])).days
        if gap <= 185:
            return dated[-1][1]
    return None


def _balance_sheet_shares_at(f: dict, date: str) -> Optional[float]:
    bs = (((f.get("Financials") or {}).get("Balance_Sheet") or {}).get("yearly") or {}).get(date) or {}
    return _num(bs.get("commonStockSharesOutstanding"))


def _shares_at(f: dict, date: str) -> tuple[Optional[float], Optional[str]]:
    """Shares on issue at a balance date, and why it can't be trusted (or None).

    EODHD carries two share counts: ``outstandingShares`` and the balance
    sheet's ``commonStockSharesOutstanding``. When both exist and disagree
    by more than SHARE_COUNT_TOLERANCE, neither is used: Rolls-Royce's
    Dec-2019 counts are 5.6bn and 5.5bn (rights-adjusted) against ~1.9bn
    actually on issue, which made a -69p year read -23p.
    """
    os_, bs = _outstanding_shares_at(f, date), _balance_sheet_shares_at(f, date)
    if os_ and bs:
        if abs(os_ - bs) / max(os_, bs) > SHARE_COUNT_TOLERANCE:
            return os_, (f"EODHD share counts disagree ({os_ / 1e6:,.0f}m outstanding vs "
                         f"{bs / 1e6:,.0f}m balance sheet)")
        return os_, None
    return (os_ or bs), None


def _inconsistent_move(f: dict, prev: str, date: str) -> Optional[str]:
    """Both EODHD share sources exist for both years but tell different
    stories: one jumps more than SHARE_JUMP_LIMIT, the other doesn't. That is
    Rolls-Royce Dec-2019: outstandingShares 1,869m -> 5,627m (+201%) while
    the balance sheet goes 5,417m -> 5,548m (+2%)."""
    vals = [_outstanding_shares_at(f, prev), _outstanding_shares_at(f, date),
            _balance_sheet_shares_at(f, prev), _balance_sheet_shares_at(f, date)]
    if not all(vals):
        return None
    os_chg, bs_chg = vals[1] / vals[0] - 1, vals[3] / vals[2] - 1
    if max(abs(os_chg), abs(bs_chg)) > SHARE_JUMP_LIMIT and abs(os_chg - bs_chg) > SHARE_JUMP_LIMIT:
        return (f"EODHD share counts move inconsistently ({os_chg:+.0%} outstanding vs "
                f"{bs_chg:+.0%} balance sheet)")
    return None


def annual_eps(sym: str, fund: Optional[dict] = None, *, include_rejected: bool = False) -> list[dict]:
    """Reported annual EPS, oldest first, from EODHD's income statements.

    ``eps`` = net income attributable to ordinary shareholders / shares on
    issue at the balance date (statutory, not underlying). ``release_date``
    is EODHD's reportDate for that period when it is a real date after the
    year end, so callers can date each figure without look-ahead; None
    otherwise. A year with no net income or no share count is left out, not
    filled.

    A year whose share count fails a check (the two EODHD sources disagree,
    they move inconsistently, or shares jump more than SHARE_JUMP_LIMIT on a
    single source) is left
    out too. With ``include_rejected=True`` those rows come back with a
    ``rejected`` reason, for the data-check report only.
    """
    f = fund if fund is not None else fundamentals(sym)
    inc = ((f.get("Financials") or {}).get("Income_Statement") or {})
    yearly = inc.get("yearly") or {}
    history = (f.get("Earnings") or {}).get("History") or {}
    out = []
    prev_shares, prev_date = None, None
    for date in sorted(yearly):
        row = yearly[date] or {}
        ni = _num(row.get("netIncomeApplicableToCommonShares"))
        if ni is None:
            ni = _num(row.get("netIncome"))
        shares, problem = _shares_at(f, date)
        if ni is None or not shares:
            prev_date = date
            continue
        if problem is None and prev_date:
            problem = _inconsistent_move(f, prev_date, date)
        if problem is None and prev_shares:
            change = shares / prev_shares - 1
            two_sources = _outstanding_shares_at(f, date) and _balance_sheet_shares_at(f, date)
            if abs(change) > SHARE_JUMP_LIMIT and not two_sources:
                problem = (f"shares on issue moved {change:+.0%} in a year on one EODHD "
                           f"source only ({prev_shares / 1e6:,.0f}m -> {shares / 1e6:,.0f}m)")
        prev_date = date
        rel = (history.get(date) or {}).get("reportDate")
        if rel and str(rel)[:10] <= date[:10]:
            rel = None  # a "report date" on or before the year end is a placeholder, not a release
        item = {
            "fiscal_end": date, "release_date": rel, "eps": ni / shares,
            "net_income": ni, "shares": shares,
            "currency": row.get("currency_symbol") or inc.get("currency_symbol"),
            "source": f"{SOURCE} income statement",
        }
        if problem:
            if include_rejected:
                out.append({**item, "rejected": problem})
            continue
        prev_shares = shares
        out.append(item)
    return out


def earnings_trends(sym: str) -> list[dict]:
    """/calendar/trends?symbols={SYMBOL}: analyst EPS/revenue estimate rows
    (``period`` 0q/+1q/0y/+1y, ``date`` = period end, stringified numbers).
    Historical snapshots are included; see ``consensus_eps``."""
    data = _get("/calendar/trends", {"symbols": sym})
    trends = (data or {}).get("trends") if isinstance(data, dict) else None
    rows = trends[0] if trends and isinstance(trends[0], list) else []
    return [r for r in rows if isinstance(r, dict)]


def consensus_eps(sym: str, after: object, rows: Optional[list[dict]] = None) -> list[dict]:
    """Consensus annual EPS (reporting currency, per share) for fiscal years
    ending after ``after`` (the last reported year end), oldest first.

    The trends feed keeps old snapshots: one fiscal year can appear as "+1y"
    (estimated a year earlier) and "0y" (current). The "0y" row wins; rows
    with no analysts or a zero estimate are dropped, never filled in."""
    cutoff = _iso(after) or ""
    rows = earnings_trends(sym) if rows is None else rows
    best: dict[str, dict] = {}
    for r in rows:
        if r.get("period") not in ("0y", "+1y") or str(r.get("date") or "") <= cutoff:
            continue
        eps, n = _num(r.get("earningsEstimateAvg")), _num(r.get("earningsEstimateNumberOfAnalysts")) or 0
        if eps is None or (eps == 0 and n == 0) or n <= 0:
            continue
        d = str(r["date"])[:10]
        if d not in best or (r["period"] == "0y" and best[d]["period"] != "0y"):
            best[d] = {"period_end": d, "period": r["period"], "eps": eps,
                       "low": _num(r.get("earningsEstimateLow")), "high": _num(r.get("earningsEstimateHigh")),
                       "analysts": int(n), "eps_30d_ago": _num(r.get("epsTrend30daysAgo")),
                       "eps_90d_ago": _num(r.get("epsTrend90daysAgo"))}
    return [best[d] for d in sorted(best)]


def known_from(row: dict) -> str:
    """The date an ``annual_eps`` figure can be used from: EODHD's reportDate,
    else the two-month ASX reporting deadline after year end. Late is safe;
    early would be look-ahead."""
    if row.get("release_date"):
        return str(row["release_date"])[:10]
    return (dt.date.fromisoformat(row["fiscal_end"][:10]) + dt.timedelta(days=61)).isoformat()


def dividends_by_year(sym: str, start: object = None) -> dict[str, float]:
    """Cash dividends per share summed by calendar year of the ex-date (unadjusted)."""
    out: dict[str, float] = {}
    for r in dividends(sym, start):
        amt = _num(r.get("unadjustedValue"))
        if amt is None:
            amt = _num(r.get("value"))
        if amt is None or not r.get("date"):
            continue
        yr = str(r["date"])[:4]
        out[yr] = out.get(yr, 0.0) + amt
    return out


@dataclass
class DebtProfile:
    """The company's latest reported balance-sheet debt picture, straight from
    EODHD fundamentals. Every figure is as-reported (no estimate); anything
    EODHD does not carry is None. Used to give Bob's capital/debt-raise card a
    *prior* leverage baseline the announcement itself rarely restates."""
    symbol: str
    as_of: Optional[str]              # balance-sheet date (YYYY-MM-DD)
    period: Optional[str]             # "quarterly" | "yearly"
    currency: Optional[str]
    gross_debt: Optional[float] = None
    cash: Optional[float] = None
    net_debt: Optional[float] = None
    total_equity: Optional[float] = None
    ebitda: Optional[float] = None
    net_debt_to_ebitda: Optional[float] = None
    gearing: Optional[float] = None   # net debt / equity (decimal, 0.66 = 66%)
    source: str = SOURCE


def _latest_statement(section: object) -> tuple[Optional[str], dict]:
    """Return (date, row) for the newest dated entry in a {date: {...}} map.
    EODHD keys these by ISO date, so string max picks the most recent."""
    if not isinstance(section, dict) or not section:
        return None, {}
    date = max(section.keys())
    return date, (section.get(date) or {})


def debt_profile(sym: str, fund: Optional[dict] = None) -> DebtProfile:
    """Latest reported debt/leverage snapshot for *sym* from EODHD fundamentals.

    Prefers the most recent balance sheet available (quarterly or yearly,
    whichever is newer). Field names match what the rest of the codebase reads
    (see shared/classifier.py): ``shortLongTermDebtTotal`` (else
    ``shortTermDebt`` + ``longTermDebt``), ``cash`` (else ``cashAndEquivalents``),
    ``netDebt``, ``totalStockholderEquity``. EBITDA comes from ``Highlights``
    (cleanest), else the latest yearly income statement.
    """
    f = fund if fund is not None else fundamentals(sym)
    fin = f.get("Financials") or {}
    bs_all = fin.get("Balance_Sheet") or {}

    cands = []
    qd, qbs = _latest_statement(bs_all.get("quarterly"))
    if qd:
        cands.append(("quarterly", qd, qbs))
    yd, ybs = _latest_statement(bs_all.get("yearly"))
    if yd:
        cands.append(("yearly", yd, ybs))
    if not cands:
        raise EODHDError(f"EODHD /fundamentals/{sym}: no balance sheet")
    period, date, bs = max(cands, key=lambda c: c[1])

    gross_debt = _num(bs.get("shortLongTermDebtTotal"))
    if gross_debt is None:
        st, lt = _num(bs.get("shortTermDebt")), _num(bs.get("longTermDebt"))
        gross_debt = (st or 0) + (lt or 0) if (st is not None or lt is not None) else None
    cash = _num(bs.get("cash"))
    if cash is None:
        cash = _num(bs.get("cashAndEquivalents"))
    net_debt = _num(bs.get("netDebt"))
    if net_debt is None and gross_debt is not None:
        net_debt = gross_debt - (cash or 0)
    equity = _num(bs.get("totalStockholderEquity"))

    ebitda = _num((f.get("Highlights") or {}).get("EBITDA"))
    if ebitda is None:
        _, inc = _latest_statement((fin.get("Income_Statement") or {}).get("yearly"))
        ebitda = _num(inc.get("ebitda"))

    nd_ebitda = (net_debt / ebitda) if (net_debt is not None and ebitda not in (None, 0)) else None
    gearing = (net_debt / equity) if (net_debt is not None and equity not in (None, 0)) else None
    ccy = (f.get("General") or {}).get("CurrencyCode")

    return DebtProfile(
        symbol=sym, as_of=date, period=period, currency=ccy,
        gross_debt=gross_debt, cash=cash, net_debt=net_debt, total_equity=equity,
        ebitda=ebitda, net_debt_to_ebitda=nd_ebitda, gearing=gearing,
    )
