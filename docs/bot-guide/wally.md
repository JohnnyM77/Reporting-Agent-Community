# Wally the Watcher

**Job:** find watchlist shares that have fallen to interesting price levels, without pretending that a low price automatically means a bargain.

Wally loads the configured watchlists, retrieves current and historical price information, checks configured target prices, and sends a report. It is a screen, not a full investment thesis.

## What Wally checks

- Stocks within **5% of their 52-week low**.
- Stocks trading **at or below a configured target/buy price**.
- Where valuation configuration exists, a 10-year price-versus-value chart using configured EPS/dividend series.
- Significant recent ASX announcements for flagged names, through the Wally news component.

A name is flagged if it meets either the near-low condition or the target-price condition. Both can apply at once.

## Inputs

Watchlists are stored under `watchlists/*.yaml`, including the JM, TII, Aussie Tech and TII75 lists. Optional targets can be stored beside an entry or in a top-level `targets` block. Valuation series live under `valuations/`.

A configured target price is only a trigger set by the investor. It is not proof that the security is undervalued, and it is not a recommendation to buy without checking the business and thesis.

## Outputs

- HTML email report with charts.
- JSON under `outputs/YYYY-MM-DD/` for the run.
- Durable dashboard payload at `docs/data/wally.json`.

## Schedule and run commands

The documented workflow is [`wally_watchlists.yml`](../../.github/workflows/wally_watchlists.yml). Standard watchlists are scheduled Tuesday and Friday. TII75 is attempted on Friday and then subject to a fortnightly gate.

Examples:

```bash
python -m wally.main --watchlist watchlists/jm_watchlist.yaml
python -m wally.main --all-standard-watchlists
python -m wally.main --all-combined
python -m wally.main --watchlist watchlists/tii75_watchlist.yaml --force
```

## Key files

- [`wally/`](../../wally/): screening implementation.
- [`watchlists/`](../../watchlists/): list definitions.
- [`valuations/`](../../valuations/): per-security valuation configuration.
- [`shared/eodhd.py`](../../shared/eodhd.py): shared market data.
- [`docs/data/wally.json`](../data/wally.json): dashboard-facing output.

## How to use Wally

Treat Wally as a **candidate generator**. A low price can reflect a genuine opportunity, a deteriorating business, or both. Read the news, revisit the thesis, and use Harry for a deeper challenge when the trigger warrants it.
