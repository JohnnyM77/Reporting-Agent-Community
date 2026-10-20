# Shared infrastructure and operational map

The agents have different jobs, but reuse common services for email, model calls, market data, security identifiers and Google Drive.

## Workflow map

| Workflow | Entry point | Main output | Runner noted in repository docs |
|---|---|---|---|
| `daily.yml` | `python agent.py` | `docs/data/bob.json`, `state_seen.json` | Ubuntu |
| `us_daily.yml` | `python us_agent.py` | `docs/data/us.json` | Ubuntu |
| `sgx_daily.yml` | `sgx_agent.py` | `docs/data/slinger.json`, seen-state file | Self-hosted Windows |
| `wally_watchlists.yml` | `python -m wally.main` | `docs/data/wally.json`, `outputs/` | Ubuntu |
| `sunday_sally_weekly_review.yml` | `python -m src.main` from `sunday-sally/` | `docs/data/sally.json` | Ubuntu |
| `ned_news.yml` / `ned_podcast.yml` | `python -m ned.main` | `docs/data/ned.json`, transcript data | Ubuntu |
| `ned_transcript.yml` | `python -m ned.main` | transcript data | Self-hosted Windows |
| `results_pack_agent.yml` | `python -m results_pack_agent.main` | `outputs/` | Ubuntu |
| `captain_hindsight.yml` | `python -m hindsight` | `docs/data/harry.json`, private store | Ubuntu |
| `theo-season.yml` | `python -m theo.cli season` | thesis records | Ubuntu |
| `theo-pages.yml` | `theo.cli` and dashboard builder | published thesis site | Ubuntu |

The repository's infrastructure notes say workflows that write `docs/data/*.json` then rebuild the dashboard and commit the updated data with `[skip ci]`.

## Shared services

| Module | Responsibility |
|---|---|
| `shared/email_service.py` | SMTP setup, message formatting, attachments and delivery transport. |
| `shared/llm.py` | Anthropic client transport, streaming, usage/error extraction and retries. |
| `shared/pdf_llm.py` | PDF attachment preparation, request-size/page limits and PDF fallback handling. |
| `shared/securities.py` | Normalises security identifiers across exchanges and common symbol formats. |
| `shared/eodhd.py` | Shared EODHD prices, FX, fundamentals and dividends. |
| `shared/gdrive.py` | Google Drive authentication, folders and file upload support. |
| `shared/asx.py` | ASX URL construction, sessions, links and PDF URL helpers. |
| `asx_fetch.py` | Recent ASX announcements for Bob and Wally. |
| `shared/events.py` | Canonical `InvestorEvent` shape for internal event exchange. |
| `scripts/build_dashboard.py` and `dashboard/` | Render the per-agent dashboard from published JSON data. |

Shared infrastructure is plumbing, not investment judgement. Each agent still owns its own prompts, thresholds, routing and failure policy.

## What is live, what is not

**Master Engine is not currently a production workflow.** The repository's `master_engine/README.md` explicitly says it is scaffolding. The aggregator, prioritiser, linker, renderer and notifier exist, but no workflow runs them. Do not describe a combined Master Engine briefing as a current automated output.

The internal event model is live as a shared schema, and Harry writes events in that shape. That is groundwork for future aggregation, not evidence that the Master Engine itself is running.

## Data and privacy boundaries

- Dashboard JSON is the durable public-facing output used by the dashboard and downstream readers.
- Harry's case files, SQLite history, behavioural profile and richer decision data belong in the private store.
- Harry's storage implementation is designed to fail clearly if the private store is required but not configured, rather than quietly placing personal records in the public repository.
- Never add API keys, passwords, private portfolio dollar data or personal case files to the public repo.

## Reading the outputs correctly

1. **A flag is not a trade instruction.** Wally and Sally generate candidates for review.
2. **A summary is not the primary evidence.** Use the ASX filing, SEC filing, SGX announcement or original transcript before making a material decision.
3. **A missing output can be a workflow failure.** Check the Actions run and logs rather than interpreting silence as “nothing happened”.
4. **An agent's confidence is not independent corroboration.** Multiple agents may share the same source data or model transport.
5. **Check the timestamp and source window.** An old dashboard payload is not a current market signal.

## Source of truth

Start with [the root README](../../README.md) and [the infrastructure map](../INFRASTRUCTURE.md), then follow each bot's entry point and workflow. Where prose documentation conflicts with current code, confirm the behaviour in code before editing the explanation.
