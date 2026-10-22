# Reporting Agent: community edition

This is a copy of a private, working portfolio-monitoring system: a team of
small agents that watch ASX, SGX and US announcements, screen watchlists,
review holdings against written theses, and email a digest every morning.
It is shared as-is, for people who want to read the code or run their own.

## The agents

Bob reads ASX announcements for every holding and writes up results days.
Singapore Slinger and Bob USA do the same for SGX and SEC filings. Ned scans
news, YouTube and podcasts. Wally screens the watchlists for value. Selling
Sally reviews holdings weekly for valuation stretch. Shorty reports the weekly
ASIC short-interest positions. Harry Hindsight is the sceptic who challenges
each thesis. Theo keeps the theses honest over time — running a "Thinking in
Bets" (Annie Duke) decision-quality interview, plus a business-quality check
(moat, financials, competition), whenever a thesis is written or reviewed — and
publishes them as slides. Esther stress-tests a single idea on demand, and
Micky's Macro maps long-horizon structural trends through to candidate
companies. README.md and CLAUDE.md describe how they fit together.

## What is different from the private copy

The owner's money stays private. Share counts, position-sized dollar figures
and position weights have been removed or replaced with `x`, the decision
ledger (`data/decisions.json`) is empty, and one thesis is not included. A
leak guard (`scripts/leak_guard.py`) checks every build of this copy against
the real numbers before it is published.

Live dashboard data, published transcripts, generated outputs, and data from
paid or licensed sources (Simply Wall St exports, the EODHD cache, subscription
price targets) are not included. Example files show the formats:
`data/decisions.example.json` and `config/tii_portfolio_targets.yaml`.

Every automatic trigger (schedules and push) has been switched
off. Nothing runs until you add your own keys and press Run in the Actions tab.

## Running it yourself

1. Fork or copy the repo.
2. Add the secrets the workflows ask for under Settings, Secrets and variables,
   Actions. The main ones are `ANTHROPIC_API_KEY`, `EODHD_API_TOKEN`,
   `EMAIL_FROM`, `EMAIL_TO` and `EMAIL_APP_PASSWORD`. Google Drive upload is
   optional.
3. Put your own tickers in `tickers.yaml`, your watchlists in `watchlists/`,
   and your theses in `theses/` (run `python -m theo.cli check` to validate).
4. Run a workflow by hand from the Actions tab. Add a `schedule:` back to any
   workflow you want on a timer.

The Singapore workflows expect a self-hosted Windows runner. Never attach a
self-hosted runner to a public repo.

## Disclaimer

Nothing here is financial advice. The theses record one person's reasoning,
including the mistakes, and are kept because the mistakes are the useful part.
