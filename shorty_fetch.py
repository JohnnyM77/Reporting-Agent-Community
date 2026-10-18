"""
shorty_fetch.py -- ASIC short position report fetch + parse.

ASIC publishes one aggregate short-position CSV per ASX trading day at a
predictable URL:

    https://download.asic.gov.au/short-selling/RR{YYYYMMDD}-001-SSDailyAggShortPos.csv

(confirmed against the live 12-Oct-2026 report; the ``-001-`` segment is
assumed to be a stable per-day sequence number, not re-verified for every
date). Reports lag by a few business days and never exist for weekends or
public holidays, so there is no index to list -- the only way to find "the
most recent report" or "the report closest to a given date" is to probe
candidate dates and see which one exists.

Columns (as published, confirmed from the live file):
    Product, Product Code, Reported Short Positions, Total Product in Issue,
    % of Total Product in Issue Reported as Short Positions

This module never guesses a figure. A row that cannot be found in a report
is absent from the returned dict -- callers render that as "not reported",
never as 0%.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import requests
except Exception:  # pragma: no cover -- requests is a standard dep across the repo
    requests = None  # type: ignore

try:
    from zoneinfo import ZoneInfo
    SYDNEY_TZ = ZoneInfo("Australia/Sydney")
except Exception:  # pragma: no cover -- zoneinfo is stdlib on 3.9+
    SYDNEY_TZ = None


Log = Callable[[str], None]


def _log(msg: str) -> None:
    print(msg, flush=True)


# --- constants ---------------------------------------------------------------

ASIC_CSV_URL_TEMPLATE = (
    "https://download.asic.gov.au/short-selling/RR{date}-001-SSDailyAggShortPos.csv"
)

# Real header row, exact text, confirmed against the live 12-Oct-2026 file.
EXPECTED_HEADERS = [
    "Product",
    "Product Code",
    "Reported Short Positions",
    "Total Product in Issue",
    "% of Total Product in Issue Reported as Short Positions",
]

_REQUEST_HEADERS = {
    # download.asic.gov.au is a plain file download, but some gov CDNs
    # reject a bare python-requests UA. Sent defensively -- never verified
    # live from this sandbox (no outbound internet here), so the first real
    # GitHub Actions run is the actual test.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ShortRow:
    product: str
    product_code: str
    reported_short_positions: int
    total_product_in_issue: int
    pct_short: float


class AsicFetchError(RuntimeError):
    """A report was found but could not be parsed (bad/changed header shape)."""


def sydney_today() -> dt.date:
    if SYDNEY_TZ is not None:
        return dt.datetime.now(SYDNEY_TZ).date()
    return dt.datetime.utcnow().date()  # degraded but harmless fallback


def fy_start_date(as_of: Optional[dt.date] = None) -> dt.date:
    """1 July of the financial year *as_of* falls in. ASX FY runs Jul-Jun."""
    d = as_of or sydney_today()
    year = d.year if d.month >= 7 else d.year - 1
    return dt.date(year, 7, 1)


def _report_url(d: dt.date) -> str:
    return ASIC_CSV_URL_TEMPLATE.format(date=d.strftime("%Y%m%d"))


def _parse_num(raw: str) -> float:
    """Strip thousands commas / a trailing % / whitespace, then float()."""
    cleaned = (raw or "").strip().replace(",", "").rstrip("%").strip()
    if not cleaned:
        raise ValueError("empty numeric field")
    return float(cleaned)


def _parse_csv_text(text: str, log: Log = _log) -> List[ShortRow]:
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = [h.strip() for h in (reader.fieldnames or [])]
    if fieldnames != EXPECTED_HEADERS:
        raise AsicFetchError(
            "ASIC CSV header shape changed -- expected "
            f"{EXPECTED_HEADERS!r}, got {fieldnames!r}. Refusing to guess a "
            "column mapping; update EXPECTED_HEADERS once the real shape is "
            "confirmed."
        )
    rows: List[ShortRow] = []
    skipped = 0
    for raw_row in reader:
        try:
            product = (raw_row["Product"] or "").strip()
            code = (raw_row["Product Code"] or "").strip().upper()
            if not code:
                skipped += 1
                continue
            rows.append(ShortRow(
                product=product,
                product_code=code,
                reported_short_positions=int(_parse_num(raw_row["Reported Short Positions"])),
                total_product_in_issue=int(_parse_num(raw_row["Total Product in Issue"])),
                pct_short=_parse_num(raw_row["% of Total Product in Issue Reported as Short Positions"]),
            ))
        except (ValueError, KeyError) as exc:
            skipped += 1
            continue
    if skipped:
        log(f"[shorty_fetch] skipped {skipped} unparsable row(s)")
    return rows


def fetch_report(d: dt.date, log: Log = _log) -> Optional[List[ShortRow]]:
    """Fetch + parse the report for exactly date *d*.

    Returns None when no report exists for that date (404 -- weekend,
    holiday, or simply not yet published). Raises AsicFetchError if a report
    exists but its shape doesn't match what this module expects -- that is
    a real problem, never silently swallowed.
    """
    if requests is None:
        raise AsicFetchError("requests is not installed")
    url = _report_url(d)
    try:
        resp = requests.get(url, headers=_REQUEST_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        log(f"[shorty_fetch] {d.isoformat()}: request failed ({exc.__class__.__name__}: {exc})")
        return None
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        log(f"[shorty_fetch] {d.isoformat()}: HTTP {resp.status_code} from {url}")
        return None
    try:
        rows = _parse_csv_text(resp.text, log=log)
    except AsicFetchError:
        raise
    if not rows:
        log(f"[shorty_fetch] {d.isoformat()}: report fetched but parsed to zero rows")
        return None
    return rows


def find_most_recent_report(
    today: Optional[dt.date] = None,
    max_back_days: int = 20,
    log: Log = _log,
) -> Tuple[Optional[dt.date], Optional[List[ShortRow]]]:
    """Probe backward from *today* (inclusive) for the newest available
    report. Never looks into the future -- a report for today or yesterday
    routinely doesn't exist yet because of ASIC's publication lag."""
    start = today or sydney_today()
    for offset in range(0, max_back_days + 1):
        d = start - dt.timedelta(days=offset)
        rows = fetch_report(d, log=log)
        if rows is not None:
            log(f"[shorty_fetch] most recent report: {d.isoformat()} ({len(rows)} rows)")
            return d, rows
    log(f"[shorty_fetch] no report found in the last {max_back_days} days back from {start.isoformat()}")
    return None, None


def find_nearest_report(
    target: dt.date,
    max_radius_days: int = 14,
    log: Log = _log,
) -> Tuple[Optional[dt.date], Optional[List[ShortRow]]]:
    """Probe outward from *target* (0, +1, -1, +2, -2, ...) for the nearest
    available report in either direction. Used for the FY-start baseline,
    where "closest to 1 July" can legitimately fall a few days either side
    of the target if it lands on a weekend/holiday."""
    rows = fetch_report(target, log=log)
    if rows is not None:
        return target, rows
    for offset in range(1, max_radius_days + 1):
        for d in (target + dt.timedelta(days=offset), target - dt.timedelta(days=offset)):
            rows = fetch_report(d, log=log)
            if rows is not None:
                log(f"[shorty_fetch] nearest report to {target.isoformat()}: "
                    f"{d.isoformat()} ({len(rows)} rows)")
                return d, rows
    log(f"[shorty_fetch] no report found within {max_radius_days} days of {target.isoformat()}")
    return None, None


def rows_by_code(rows: List[ShortRow]) -> Dict[str, ShortRow]:
    """First occurrence per Product Code. ASIC's file shouldn't carry
    duplicate codes, but first-wins is the safe default if it ever does."""
    out: Dict[str, ShortRow] = {}
    for r in rows:
        out.setdefault(r.product_code, r)
    return out


def rank_map(rows: List[ShortRow]) -> Dict[str, int]:
    """Product Code -> 1-based rank by % short, descending (1 = most shorted
    stock on the ASX that day)."""
    ordered = sorted(rows, key=lambda r: r.pct_short, reverse=True)
    return {r.product_code: i + 1 for i, r in enumerate(ordered)}


# ASIC's Product column is the company name plus a trailing security-type
# descriptor ("DRONESHIELD LIMITED ORDINARY", "LENDLEASE GROUP FPO/UNITS
# STAPLED") -- stripped here so a watchlist card can show a real name
# without relying on tickers.yaml, which only names the portfolio.
_ASIC_SUFFIX_RE = re.compile(
    r"\s+(ORDINARY FULLY PAID|ORDINARY/UNITS FULLY PAID|FPO/UNITS STAPLED|"
    r"STAPLED SECURITIES|UNITS FULLY PAID|ORDINARY|FPO|UNITS)\s*$",
    re.IGNORECASE,
)


def _title_case_preserve_acronyms(s: str) -> str:
    """Title-case each word, except a short (<=4 char) all-caps word, which
    is left alone on the assumption it's a ticker-like acronym (BHP, CSL,
    REA) rather than a word that wants sentence casing."""
    words = []
    for word in s.split(" "):
        if word.isalpha() and word.isupper() and len(word) <= 4:
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def clean_product_name(raw: str) -> str:
    """ASIC's ALL-CAPS "DRONESHIELD LIMITED ORDINARY" -> "Droneshield
    Limited". Best-effort cosmetics only -- never used to decide anything,
    just to make a watchlist card readable without a curated name."""
    name = _ASIC_SUFFIX_RE.sub("", raw or "").strip()
    return _title_case_preserve_acronyms(name)


def load_watchlist_universe(
    exclude: Optional[set] = None,
    log: Log = _log,
) -> Tuple[Dict[str, str], Optional[str]]:
    """{ticker: watchlist_name} for every ASX ticker across Wally's five
    standard watchlists (watchlists/*.yaml), de-duplicated in the exact
    priority order Wally itself uses -- Income > JM > Aussie Tech >
    Cornerstone > Nap Taker (``wally.config.STANDARD_WATCHLISTS``) -- so a
    ticker carried by more than one list is attributed to the
    highest-priority one, same as Wally's own screen.

    Only reuses the lightweight YAML loader (``wally.watchlist_loader``),
    not Wally's main pipeline -- that pulls in EODHD fetches, chart
    rendering and an LLM shortlist call, none of which Shorty needs just
    to know which tickers are on which list.

    These watchlists mix in US and UK names (Nap Taker holds AMD, MSFT;
    Cornerstone holds AUTO, LSEG) which ASIC's ASX-only short report can
    never cover. The only reliable marker is the literal ``.AX`` suffix
    Wally's loader puts on every ASX entry (``ARB.AX``) and never on a
    non-ASX one (bare ``AMD``, ``AUTO``) -- non-``.AX`` tickers are
    dropped rather than guessed at.

    *exclude* (the portfolio tickers, already covered in their own
    section) is removed from the result so a holding never shows up
    twice under a different heading.

    Returns (universe, error). On any failure to import or load Wally's
    watchlists, universe is ``{}`` and error names the reason -- callers
    must render that as a visible note, never a silently empty section
    (same "half-broken must never look clean" rule as the rest of this
    agent).
    """
    try:
        from wally.config import STANDARD_WATCHLISTS
        from wally.watchlist_loader import load_watchlist
    except Exception as exc:
        msg = f"could not import Wally's watchlist loader ({exc.__class__.__name__}: {exc})"
        log(f"[shorty_fetch] {msg}")
        return {}, msg

    repo_root = Path(__file__).resolve().parent
    exclude = exclude or set()
    universe: Dict[str, str] = {}
    loaded_any = False
    for rel in STANDARD_WATCHLISTS:
        path = repo_root / rel
        try:
            wl = load_watchlist(path)
        except Exception as exc:
            log(f"[shorty_fetch] could not load {rel}: {exc.__class__.__name__}: {exc}")
            continue
        loaded_any = True
        for ticker in wl.tickers:
            if not ticker.endswith(".AX"):
                continue
            code = ticker[:-3]
            if code in exclude or code in universe:
                continue
            universe[code] = wl.name

    if not loaded_any:
        msg = "none of Wally's standard watchlists could be loaded"
        log(f"[shorty_fetch] {msg}")
        return {}, msg
    log(f"[shorty_fetch] watchlist universe: {len(universe)} ASX ticker(s) "
        f"across {len(STANDARD_WATCHLISTS)} watchlist(s)")
    return universe, None


def load_portfolio_tickers(tickers_yaml_path: Optional[Path] = None) -> Dict[str, str]:
    """{ticker: company name} for every ASX ticker in tickers.yaml, minus
    the ETFs -- short interest on an index ETF isn't a meaningful signal
    the way it is for a single stock, and etf_tickers already exists as the
    exclusion list the rest of the repo uses for the same purpose."""
    path = tickers_yaml_path or (Path(__file__).resolve().parent / "tickers.yaml")
    try:
        import yaml
    except Exception as exc:
        _log(f"[shorty_fetch] PyYAML unavailable: {exc}")
        return {}
    if not path.exists():
        _log(f"[shorty_fetch] no tickers.yaml at {path}")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        _log(f"[shorty_fetch] could not parse {path}: {exc}")
        return {}
    asx = data.get("asx") or {}
    if not isinstance(asx, dict):
        return {}
    etfs = set(data.get("etf_tickers") or [])
    return {
        str(k).strip().upper(): str(v).strip()
        for k, v in asx.items()
        if str(k).strip().upper() not in etfs
    }
