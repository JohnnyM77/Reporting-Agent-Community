"""Import reported annual EPS from a Simply Wall St (SWS) company export.

The SWS export is one sheet: field names down column A, values across the
row. Every date in it is a **Unix timestamp**: whole seconds since
1970-01-01 00:00 UTC (1782777600 = 2026-06-30). In Excel:
``=A1/86400+DATE(1970,1,1)`` and format the cell as a date.

What this takes from the export, and nothing else:

* ``past_earnings_per_share_ltm_history`` + ``..._offset``: reported EPS (A$)
  for each financial year, offset 0 = the year ending
  ``past_last_earnings_update_annual``, -1 the year before, and so on.
* ``dividend_historical_dividend_payments_date``: SWS's dividend dates. ASX
  companies declare dividends with their results, and these sit on or a few
  days after the results release, so the first one after a year end is used
  as that year's release date. Using a date a few days late never applies EPS
  before the market saw it; a date too early would.
* ``dividend_payout_ratio_history`` at each year end x that year's EPS gives
  the year's dividend per share (only for the old value-chart workbook; the
  wedge ignores dividends).

SWS gives annual EPS only. Half-year EPS goes in ``half_year_eps:`` in the
valuation YAML by hand, with its source; this importer never invents it.

Usage (from sunday-sally/):
    python -m src.sws_import path/to/SWS_Data.xlsx --ticker PWH          # print
    python -m src.sws_import path/to/SWS_Data.xlsx --ticker PWH --write  # update YAML
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

RELEASE_WINDOW_DAYS = 100     # a results date must fall this soon after year end


def unix_to_date(x) -> dt.date:
    return dt.datetime.fromtimestamp(int(float(x)), dt.timezone.utc).date()


def read_sws_rows(path: str | Path) -> dict[str, list]:
    """Field name -> values, from the SWS .xlsx export or its .csv form
    (data/sws_csv/ASX_<TICKER>.csv)."""
    if str(path).lower().endswith(".csv"):
        import csv
        rows: dict[str, list] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            for r in csv.reader(fh):
                if r and r[0].strip():
                    rows[r[0].strip()] = [_num(v) for v in r[1:] if v not in (None, "")]
        return rows
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows: dict[str, list] = {}
    for r in ws.iter_rows(values_only=True):
        if not r or r[0] in (None, ""):
            continue
        rows[str(r[0]).strip()] = [v for v in r[1:] if v not in (None, "")]
    return rows


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def asx_deadline(period_end: dt.date) -> dt.date:
    """Last day of the second month after period end: ASX Listing Rules
    4.2A/4.3A (half-year and preliminary final reports). A result is never
    released later than this, so it is a safe (late, never early) date."""
    y, m = period_end.year, period_end.month + 2
    if m > 12:
        y, m = y + 1, m - 12
    nxt = dt.date(y + (m == 12), (m % 12) + 1, 1)
    return nxt - dt.timedelta(days=1)


def _shift_years(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:                      # 29 Feb
        return d.replace(year=d.year + years, day=28)


def annual_eps_rows(rows: dict[str, list], source_label: str) -> list[dict]:
    """One dict per financial year, oldest first, EPS in cents."""
    eps = rows.get("past_earnings_per_share_ltm_history") or []
    offsets = rows.get("past_earnings_per_share_ltm_history_offset") or list(range(0, -len(eps), -1))
    # The LTM series is anchored on the LATEST reported period, which is a
    # half-year end when the latest result was a half (BHP export: Dec 2025),
    # not on the last financial-year end.
    anchor_raw = (rows.get("past_last_earnings_update") or rows.get("past_last_earnings_update_annual") or [None])[0]
    annual_raw = (rows.get("past_last_earnings_update_annual") or [anchor_raw])[0]
    if not eps or anchor_raw is None:
        raise ValueError("SWS export has no past_earnings_per_share_ltm_history / last earnings date")
    anchor = unix_to_date(anchor_raw)
    fy_end_month = unix_to_date(annual_raw).month

    div_dates = sorted(unix_to_date(x) for x in rows.get("dividend_historical_dividend_payments_date") or [])
    payout_dates = [unix_to_date(x) for x in rows.get("dividend_payout_ratio_history_date") or []]
    payout = dict(zip(payout_dates, rows.get("dividend_payout_ratio_history") or []))

    out = []
    for off, e in zip(offsets, eps):
        if e is None:
            continue
        end = _shift_years(anchor, int(off))
        if end.month == fy_end_month:
            period = f"FY{end.year}"
        else:   # a half-year end: TTM to that date, labelled by the FY it falls in
            fy = end.year + (1 if end.month > fy_end_month else 0)
            period = f"1H{fy} TTM"
        deadline = asx_deadline(end)
        div = next((d for d in div_dates if end < d <= end + dt.timedelta(days=RELEASE_WINDOW_DAYS)), None)
        # Both are on or after the real release; take the earlier of the two.
        if div is not None and div <= deadline:
            release, date_note = div, "release date = SWS dividend date (on or just after the results)"
        else:
            release, date_note = deadline, "release date = ASX two-month reporting deadline (late, never early)"
        eps_c = round(float(e) * 100, 3)
        pr = payout.get(end)
        row = {
            "date": release.isoformat(),
            "period": period,
            "period_end": end.isoformat(),
            "ttm_eps": eps_c,
            "ttm_div": round(float(pr) * eps_c, 2) if pr is not None else None,
            "source": source_label,
            "notes": f"Reported {'annual' if period.startswith('FY') else 'trailing-12-month'} EPS (SWS); {date_note}",
        }
        out.append(row)
    ccy = (rows.get("currency_info_reporting_currency_iso") or [""])[0]
    if ccy:
        for r in out:
            r["currency"] = str(ccy)
    return sorted(out, key=lambda r: r["period_end"])


def _yaml_row(r: dict) -> str:
    def q(v):
        return "null" if v is None else (f'"{v}"' if isinstance(v, str) else f"{v:g}" if isinstance(v, float) else str(v))
    keys = ("date", "period", "period_end", "ttm_eps", "ttm_div", "currency", "source", "notes")
    return "  - {" + ", ".join(f"{k}: {q(r.get(k))}" for k in keys if k in r) + "}"


def render_earnings_block(rows: list[dict]) -> str:
    return "earnings:\n" + "\n".join(_yaml_row(r) for r in rows) + "\n"


def replace_earnings_block(yaml_text: str, new_block: str) -> str:
    """Swap the top-level ``earnings:`` list in place, keeping comments and
    every other key (half_year_eps, period_notes, multiples...) untouched."""
    lines = yaml_text.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if re.match(r"^earnings:\s*$", l)), None)
    if start is None:
        return yaml_text.rstrip("\n") + "\n\n" + new_block
    end = start + 1
    while end < len(lines) and (lines[end].startswith("  ") or not lines[end].strip()):
        end += 1
    # keep blank lines that separate the next block
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return "".join(lines[:start]) + new_block + "".join(lines[end:])


def main(argv: list[str] | None = None) -> None:
    from .pathing import repo_root
    from .value_wedge import normalise_ticker, ticker_slug

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("xlsx")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--write", action="store_true", help="replace the earnings: list in valuations/<ticker>.yaml")
    a = ap.parse_args(argv)

    stamp = re.search(r"(\d{6})", Path(a.xlsx).name)
    label = f"SWS export {stamp.group(1)}" if stamp else f"SWS export {Path(a.xlsx).name}"
    rows = annual_eps_rows(read_sws_rows(a.xlsx), label)
    block = render_earnings_block(rows)
    print(block)
    if a.write:
        path = repo_root() / "valuations" / f"{ticker_slug(normalise_ticker(a.ticker))}.yaml"
        path.write_text(replace_earnings_block(path.read_text(encoding="utf-8"), block), encoding="utf-8")
        print(f"[sws_import] wrote {len(rows)} EPS rows to {path}")


if __name__ == "__main__":
    main()
