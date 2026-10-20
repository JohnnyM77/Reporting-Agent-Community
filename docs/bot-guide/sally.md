# Sunday Sally

**Job:** identify holdings that may be stretched on valuation and deserve a fresh look before the price turns.

Sally is a weekly valuation-review agent. She uses the portfolio universe in `tickers.yaml`, price/fundamental data and company history to identify names near 52-week highs and assess whether valuation looks rich relative to that company's own history.

## What Sally does

- Reviews the configured portfolio each Sunday.
- Flags potential trim candidates using valuation and price context.
- Pulls significant ASX announcements from the preceding 90 days for flagged names, including results, guidance changes, capital raisings, M&A, board changes, halts and price-sensitive announcements.
- Produces a review memo and spreadsheet with supporting evidence.

**Sally does not automatically sell shares.** Her job is to force a valuation conversation, not to execute a transaction.

## Verdicts and hand-off

The architecture notes describe Sally's verdicts as:

- **Trim candidate** (Tier 3)
- **Hold but stop adding** (Tier 2)
- **Watch only** (Tier 1)

Harry consumes Sally's published output and applies additional deterministic gates before a deeper sceptical review. In particular, Harry can treat a trim-candidate flag on a holding as a sell-review trigger. The mapping is explicit in Harry's configuration and code; it does not mean Sally herself issues an automatic sell order.

## Outputs

Each run writes to `data/outputs/YYYY/YYYY-MM-DD Weekly Review/`, including:

- `summary_email.md`
- `run_log.json`
- For each flagged ticker: `memo.md`, `valuation_review.xlsx`, `handoff_payload.json` and an announcement index.

The dashboard-facing payload is `docs/data/sally.json`.

## Schedule

Workflow: [`sunday_sally_weekly_review.yml`](../../.github/workflows/sunday_sally_weekly_review.yml). The documented cron is `0 0 * * 0`, which is 08:00 Singapore time on Sunday.

## Key files

- [`sunday-sally/README.md`](../../sunday-sally/README.md)
- [`sunday-sally/src/`](../../sunday-sally/src/)
- [`docs/data/sally.json`](../data/sally.json)
- [`hindsight/adapters.py`](../../hindsight/adapters.py), which reads Sally's published output.

## How to use Sally

A high valuation percentile is a warning light, not a sell signal on its own. Check whether the business outlook, competitive position and thesis have changed, and whether the price already reflects that. The point is to make the decision deliberately, not to trade mechanically.
