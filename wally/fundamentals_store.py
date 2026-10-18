"""
wally/fundamentals_store.py

Persistent EPS + dividend cache for Wally.
Store: fundamentals/{ticker_slug}.json  e.g. fundamentals/rmd_ax.json

Source: EODHD only (shared/eodhd.py), every market.
  - annual EPS  = EODHD income statement net income / shares on issue
  - release date per year = EODHD reportDate, else the two-month deadline
    after year end (no look-ahead when charting)
  - dividends   = EODHD /div, summed by calendar year of the ex-date

A cache file written by an earlier source (yfinance, Alpha Vantage, FMP,
SWS) is treated as stale and rebuilt from EODHD; its old figures are not
carried over. A year EODHD has no figure for is left out, never filled.

YAML overrides in valuations/ always win over any API data: they are
hand-entered from the company's own reports.
"""

import datetime
import json
from pathlib import Path

import yaml

PROVIDER = "eodhd"
# Bump when the EODHD derivation changes, so caches built by the old rules
# are rebuilt. 2: share-count check + no report date on/before year end.
PROVIDER_VERSION = 2


def _slug(ticker: str) -> str:
    return ticker.lower().replace(".", "_")


def _store_path(ticker: str) -> Path:
    return Path("fundamentals") / f"{_slug(ticker)}.json"


def load(ticker: str) -> dict:
    """Load JSON store for ticker. Returns {} if not found or corrupt."""
    path = _store_path(ticker)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[fundamentals] Load error for {ticker}: {e}")
        return {}


def save(ticker: str, data: dict) -> None:
    """Write JSON store for ticker."""
    path = _store_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[fundamentals] Saved cache for {ticker}")


def is_stale(data: dict) -> bool:
    """
    Returns True if cache needs refreshing:
    - Written by anything other than EODHD
    - Empty or missing annual_eps_cents
    - last_updated > 90 days ago
    - Most recent year in annual_eps_cents is > 14 months behind today
    """
    if not data or not data.get("annual_eps_cents"):
        return True
    if data.get("provider") != PROVIDER or data.get("provider_version") != PROVIDER_VERSION:
        return True
    try:
        last = datetime.date.fromisoformat(data["last_updated"])
        if (datetime.date.today() - last).days > 90:
            return True
    except Exception:
        return True
    eps = data.get("annual_eps_cents", {})
    if eps:
        latest_year = max(int(y) for y in eps.keys())
        current_year = datetime.date.today().year
        months_lag = (current_year - latest_year) * 12
        if months_lag > 14:
            return True
    return False


def _fetch_eodhd(ticker: str) -> tuple[dict, dict, dict]:
    """
    Annual EPS (cents), dividends (cents) and EPS release dates from EODHD.
    Returns ({}, {}, {}) when EODHD has nothing; the reason is logged.
    """
    try:
        import sys
        repo_root = str(Path(__file__).resolve().parents[1])
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from shared import eodhd
        from shared.securities import US

        sym = eodhd.symbol(ticker, default_exchange=US)
        eps: dict = {}
        release: dict = {}
        for row in eodhd.annual_eps(sym):
            yr = row["fiscal_end"][:4]
            eps[yr] = round(row["eps"] * 100, 2)
            release[yr] = eodhd.known_from(row)
        div = {yr: round(v * 100, 2) for yr, v in eodhd.dividends_by_year(sym).items()}
        print(f"[fundamentals] EODHD {sym}: {len(eps)} EPS years, {len(div)} div years", flush=True)
        return eps, div, release
    except Exception as e:
        print(f"[fundamentals] EODHD fetch failed for {ticker}: {e}", flush=True)
        return {}, {}, {}


def _apply_yaml_overrides(ticker: str, eps: dict, div: dict) -> tuple[dict, dict]:
    """
    Load valuations/{slug}.yaml and apply overrides.
    YAML values always win. Returns updated (eps, div).
    """
    yaml_path = Path("valuations") / f"{_slug(ticker)}.yaml"
    if not yaml_path.exists():
        return eps, div
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        series = data.get("series", {}) or {}
        yaml_eps = series.get("eps", {}) or {}
        yaml_div = series.get("dividend", {}) or {}
        override_count = 0
        for yr, val in yaml_eps.items():
            eps[str(yr)] = float(val)
            override_count += 1
        for yr, val in yaml_div.items():
            div[str(yr)] = float(val)
        if override_count:
            print(f"[fundamentals] Applied {override_count} YAML overrides for {ticker}")
    except Exception as e:
        print(f"[fundamentals] YAML override error for {ticker}: {e}")
    return eps, div


def get_fundamentals(ticker: str) -> dict:
    """
    Main entry point called by value_chart_builder.py and spreadsheet.py.

    Returns dict:
      {
        "annual_eps_cents":    {"2016": 32.1, "2017": 38.4, ...},
        "annual_div_cents":    {"2016": 5.8, ...},
        "quarterly_eps_cents": {},            # EODHD path is annual only
        "eps_release_dates":   {"2016": "2016-08-25", ...},
      }

    EODHD only; YAML series overrides always win.
    """
    stored = load(ticker)

    if not is_stale(stored):
        eps = dict(stored.get("annual_eps_cents", {}))
        div = dict(stored.get("annual_div_cents", {}))
        release = dict(stored.get("eps_release_dates", {}))
        eps, div = _apply_yaml_overrides(ticker, eps, div)
        return {"annual_eps_cents": eps, "annual_div_cents": div,
                "quarterly_eps_cents": {}, "eps_release_dates": release}

    print(f"[fundamentals] Cache stale for {ticker} — fetching from EODHD...")
    eps, div, release = _fetch_eodhd(ticker)
    if not eps and stored.get("provider") == PROVIDER and stored.get("provider_version") == PROVIDER_VERSION:
        # EODHD down this run: keep the last EODHD figures rather than nothing.
        eps = dict(stored.get("annual_eps_cents", {}))
        div = dict(stored.get("annual_div_cents", {}))
        release = dict(stored.get("eps_release_dates", {}))

    api_eps = dict(eps)
    eps, div = _apply_yaml_overrides(ticker, eps, div)
    sources = {yr: (PROVIDER if api_eps.get(yr) == v else "valuations_yaml") for yr, v in eps.items()}

    if eps or div:
        save(ticker, {
            "ticker": ticker,
            "provider": PROVIDER,
            "provider_version": PROVIDER_VERSION,
            "last_updated": str(datetime.date.today()),
            "annual_eps_cents": eps,
            "annual_div_cents": div,
            "eps_release_dates": release,
            "quarterly_eps_cents": {},
            "sources": sources,
        })

    return {"annual_eps_cents": eps, "annual_div_cents": div,
            "quarterly_eps_cents": {}, "eps_release_dates": release}
