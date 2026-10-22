# mike/series.py
#
# EODHD /fundamentals record -> one clean row per financial year (and the
# latest interim cash-flow periods, for cash-burn work).
#
# Plumbing only. Every figure is a field EODHD returned, or plain arithmetic
# on those fields (FCF = CFO - capex, net debt = gross debt - cash). Nothing
# is estimated: a blank stays None and the calculation that needs it says it
# could not be done (framework rule 8.1: never silently substitute).
#
# Field names are exactly those in .claude/skills/eodhd-api/references/
# endpoints/fundamentals-data.md (Financials::<Statement>::yearly|quarterly).

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


def num(v: object) -> Optional[float]:
    try:
        f = float(v)  # EODHD sends most numbers as strings
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _first(row: dict, *keys: str) -> Optional[float]:
    for k in keys:
        v = num(row.get(k))
        if v is not None:
            return v
    return None


@dataclass
class YearRow:
    date: str                                  # balance date, e.g. 2026-06-30
    revenue: Optional[float] = None
    ebit: Optional[float] = None
    ebitda: Optional[float] = None
    pbt: Optional[float] = None
    tax: Optional[float] = None
    npat: Optional[float] = None
    interest: Optional[float] = None
    cfo: Optional[float] = None
    capex: Optional[float] = None
    fcf: Optional[float] = None                # CFO - capex (EODHD capitalExpenditures)
    sbc: Optional[float] = None
    equity_issued: Optional[float] = None      # issuanceOfCapitalStock
    dividends_paid: Optional[float] = None
    equity: Optional[float] = None
    debt: Optional[float] = None               # shortLongTermDebtTotal (includes lease liabilities)
    leases: Optional[float] = None
    cash: Optional[float] = None
    net_debt: Optional[float] = None
    total_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    goodwill: Optional[float] = None
    intangibles: Optional[float] = None        # goodwill + other intangibles
    shares: Optional[float] = None
    notes: list[str] = field(default_factory=list)

    @property
    def fy(self) -> str:
        return "FY" + self.date[2:4]

    @property
    def eps(self) -> Optional[float]:
        if self.npat is None or not self.shares:
            return None
        return self.npat / self.shares

    @property
    def ebit_margin(self) -> Optional[float]:
        if self.ebit is None or not self.revenue or self.revenue <= 0:
            return None
        return self.ebit / self.revenue

    @property
    def tax_rate(self) -> float:
        """Effective rate from the P&L, bounded to 0-35%; 30% when it is not meaningful."""
        if self.pbt and self.pbt > 0 and self.tax is not None:
            return max(0.0, min(0.35, self.tax / self.pbt))
        return 0.30

    @property
    def nopat(self) -> Optional[float]:
        return None if self.ebit is None else self.ebit * (1 - self.tax_rate)

    @property
    def invested_capital(self) -> Optional[float]:
        if self.equity is None:
            return None
        return self.equity + (self.debt or 0.0) - (self.cash or 0.0)

    @property
    def capital_employed(self) -> Optional[float]:
        if self.total_assets is None or self.current_liabilities is None:
            return None
        return self.total_assets - self.current_liabilities

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(fy=self.fy, eps=self.eps, ebit_margin=self.ebit_margin,
                 tax_rate=self.tax_rate, nopat=self.nopat,
                 invested_capital=self.invested_capital)
        return d


def statement_currency(fund: dict) -> Optional[str]:
    fin = fund.get("Financials") or {}
    for st in ("Income_Statement", "Balance_Sheet", "Cash_Flow"):
        c = (fin.get(st) or {}).get("currency_symbol")
        if c:
            return c
    return (fund.get("General") or {}).get("CurrencyCode")


def _row(date: str, i: dict, b: dict, c: dict) -> YearRow:
    r = YearRow(date=date)
    r.revenue = _first(i, "totalRevenue")
    r.npat = _first(i, "netIncome", "netIncomeApplicableToCommonShares")
    r.pbt = _first(i, "incomeBeforeTax")
    r.tax = _first(i, "incomeTaxExpense", "taxProvision")
    ie = _first(i, "interestExpense")
    r.interest = abs(ie) if ie is not None else None
    r.ebit = _first(i, "ebit", "operatingIncome")
    if r.ebit is None and r.pbt is not None:
        r.ebit = r.pbt + (r.interest or 0.0)
        r.notes.append("EBIT = PBT + interest expense (EODHD had no EBIT)")
    r.ebitda = _first(i, "ebitda")
    if r.ebitda is None and r.ebit is not None:
        da = _first(i, "depreciationAndAmortization", "reconciledDepreciation") or _first(c, "depreciation")
        if da is not None:
            r.ebitda = r.ebit + abs(da)
            r.notes.append("EBITDA = EBIT + D&A (EODHD had no EBITDA)")

    r.cfo = _first(c, "totalCashFromOperatingActivities")
    capex = _first(c, "capitalExpenditures")
    r.capex = abs(capex) if capex is not None else None
    if r.cfo is not None:
        r.fcf = r.cfo - (r.capex or 0.0)
    sbc = _first(c, "stockBasedCompensation")
    r.sbc = abs(sbc) if sbc is not None else None
    iss = _first(c, "issuanceOfCapitalStock")
    r.equity_issued = max(0.0, iss) if iss is not None else None
    dp = _first(c, "dividendsPaid")
    r.dividends_paid = abs(dp) if dp is not None else None

    r.equity = _first(b, "totalStockholderEquity")
    r.debt = _first(b, "shortLongTermDebtTotal")
    if r.debt is None:
        st, lt = _first(b, "shortTermDebt"), _first(b, "longTermDebt")
        if st is not None or lt is not None:
            r.debt = (st or 0.0) + (lt or 0.0)
    r.leases = _first(b, "capitalLeaseObligations")
    r.cash = _first(b, "cashAndShortTermInvestments", "cash")
    if r.debt is not None or r.cash is not None:
        r.net_debt = (r.debt or 0.0) - (r.cash or 0.0)
    r.total_assets = _first(b, "totalAssets")
    r.current_liabilities = _first(b, "totalCurrentLiabilities")
    r.goodwill = _first(b, "goodWill")
    ia = _first(b, "intangibleAssets")
    if r.goodwill is not None or ia is not None:
        r.intangibles = (r.goodwill or 0.0) + (ia or 0.0)
    r.shares = _first(b, "commonStockSharesOutstanding")
    return r


def annual_rows(fund: dict) -> list[YearRow]:
    """Every financial year EODHD has, oldest first. A year with neither
    revenue nor NPAT is EODHD padding and is dropped."""
    fin = fund.get("Financials") or {}
    inc = (fin.get("Income_Statement") or {}).get("yearly") or {}
    bal = (fin.get("Balance_Sheet") or {}).get("yearly") or {}
    cfs = (fin.get("Cash_Flow") or {}).get("yearly") or {}
    rows = []
    for date in sorted(set(inc) | set(bal) | set(cfs)):
        r = _row(date, inc.get(date) or {}, bal.get(date) or {}, cfs.get(date) or {})
        if r.revenue is None and r.npat is None:
            continue
        rows.append(r)
    return rows


def interim_cash_flows(fund: dict, n: int = 4) -> list[dict]:
    """The latest interim (quarterly/half-year) cash-flow periods EODHD holds,
    newest last: {date, cfo, capex, fcf}. Used for recent cash burn only."""
    fin = fund.get("Financials") or {}
    q = (fin.get("Cash_Flow") or {}).get("quarterly") or {}
    out = []
    for date in sorted(q)[-n:]:
        c = q[date] or {}
        cfo = _first(c, "totalCashFromOperatingActivities")
        if cfo is None:
            continue
        capex = _first(c, "capitalExpenditures")
        out.append({"date": date, "cfo": cfo, "capex": abs(capex) if capex is not None else None,
                    "fcf": cfo - (abs(capex) if capex is not None else 0.0)})
    return out
