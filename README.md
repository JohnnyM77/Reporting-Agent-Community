# Investing Research & Intelligence Agents

This repository contains a collection of Python agents and scheduled workflows that support an individual investor's research process. The system ingests company announcements, market data, news and research; applies rule-based screening and model-assisted analysis; and publishes reports, dashboard data and review artifacts.

**This is not just Bob the Bot.** Bob is one agent in a wider toolkit. The current codebase includes watchlist screening, valuation/sell-discipline reviews, news and macro research, thesis tracking, skeptical post-mortems, regional filing monitors, short-interest reporting, and on-demand company analysis.

## Start here

- **[Full agent workflow map](bot-guide/workflow-matrix.md)** — the end-to-end matrix requested for each agent: inputs and sources, processing, prompts/model/tooling, and outputs/destinations.
- **[Investing Bot Guide](bot-guide/README.md)** — plain-English guide to each agent, schedules, limitations and code entry points.
- **[Shared infrastructure map](docs/INFRASTRUCTURE.md)** — workflow-to-entry-point map and shared services.
- **[Dashboard data](docs/data/)** — agent JSON outputs consumed by the dashboard builder.
- **[Workflow definitions](.github/workflows/)** — schedules, manual inputs, runners and job steps.

## Agents at a glance

| Agent / workflow | Purpose | Main entry point |
|---|---|---|
| **Bob the Bot (ASX)** | Monitors portfolio ASX announcements, classifies them, summarises routine items and deeply analyses selected material events. | [`agent.py`](agent.py), [`prompts.py`](prompts.py) |
| **Bob USA** | Monitors configured US companies' SEC filings. | [`us_agent.py`](us_agent.py) |
| **Singapore Slinger** | Monitors SGX announcements in a separate runner/fetch pipeline. | [`sgx_agent.py`](sgx_agent.py) |
| **Wally** | Screens configured watchlists for price/valuation conditions and packages candidates with context. | [`wally/main.py`](wally/main.py) |
| **Selling Sally** | Compares price with valuation ranges and historical multiples; surfaces sell/valuation review signals. | [`sunday-sally/src/main.py`](sunday-sally/src/main.py) |
| **Ned** | Scans configured news, RSS, newsletters, YouTube and transcript sources for relevant information. | [`ned/main.py`](ned/main.py) |
| **Micky's Macro** | Converts selected newsletters and macro research into structural-trend dossiers and company candidates. | [`mickys_macro/main.py`](mickys_macro/main.py) |
| **Harry / Captain Hindsight** | Applies deterministic gates and skeptical model reviews to portfolio events, theses and decisions. | [`hindsight/runner.py`](hindsight/runner.py) |
| **Theo** | Maintains structured thesis records and generates thesis views, drift signals and pre-results review material. | [`theo/cli.py`](theo/cli.py) |
| **Esther the Wrestler** | On-demand company narrative, valuation and thesis challenge analysis. | [`esther/main.py`](esther/main.py) |
| **Shorty** | Compares ASIC short-position reports and produces a weekly digest. | [`shorty_agent.py`](shorty_agent.py) |
| **Results Pack Agent** | Builds a fuller analysis pack around a company results announcement. | [`results_pack_agent/`](results_pack_agent) |

The repository also has separate podcast/transcript workflows, dashboard rendering and publication, and shared utilities. A bot, a scheduled workflow and a dashboard card are not necessarily the same thing.

## Typical system flow

1. **Ingest:** workflows retrieve filings, prices, newsletters, feeds, transcripts or existing agent outputs.
2. **Prepare:** code normalises identifiers, removes duplicates, classifies documents/events and applies deterministic rules.
3. **Analyse:** prompt modules define model tasks and output contracts. Model calls are selective where the implementation has gates or caps.
4. **Deliver:** agents may email digests, save documents to Google Drive, write JSON under `docs/data/`, create reports/workbooks, or keep private review artifacts.
5. **Publish:** the dashboard builder combines dashboard-facing JSON into `docs/index.html`; the Pages workflow is the shared publisher for the site and Theo slides.

See the [workflow matrix](bot-guide/workflow-matrix.md) for each agent's concrete inputs, prompts/tools and outputs, and the [infrastructure map](docs/INFRASTRUCTURE.md) for workflow and shared-service details.

## Important operational notes

- **Read the workflow YAML, not just a bot's name, to establish when it runs.** Some workflows are scheduled; others are manual-only or support several run modes. Harry's event-triggered chaining is currently disabled in its workflow, so do not assume it runs whenever another agent completes.
- **Treat flags as prompts for investigation, not trade instructions.** These agents support research and discipline; they do not replace checking primary sources or exercising investment judgment.
- **Dashboard JSON is not necessarily the complete record.** Some agents keep richer artifacts or state outside `docs/data/`, including workflow-local or private storage.
- **Master Engine is scaffolding, not a currently scheduled production agent.** See [`master_engine/README.md`](master_engine/README.md).
- **Protect private portfolio data.** The repository documentation warns that the GitHub Pages site and community edition are public. Never add position dollar amounts, share counts, portfolio weights, credentials or other private information to public-facing files. Existing safeguards include [`shared/public_safety.py`](shared/public_safety.py) and [`scripts/leak_guard.py`](scripts/leak_guard.py).

## Local development

Most components are Python modules, but their dependencies and runtime assumptions differ. Some workflows use GitHub-hosted Ubuntu runners; SGX and certain transcript tasks use a self-hosted Windows runner. Check the relevant workflow and agent README before running locally.

Examples (from the repository root):

```bash
# Bob — ASX announcements
python agent.py

# Wally — run all configured watchlists in combined mode
python -m wally.main --all-combined

# Harry — run a named holding review
python -m hindsight sell NHC

# Inspect the available Theo commands
python -m theo.cli --help
```

These are examples, not a guarantee that every optional service or secret is configured on a local machine. Use each agent's own README and workflow for its current flags, environment requirements and dry-run options.

## Documentation maintenance

When an agent's data source, prompt contract, workflow trigger, model/tool integration or output changes, update its page in [`bot-guide/`](bot-guide/README.md) and the [workflow matrix](bot-guide/workflow-matrix.md) in the same change. Mark uncertain or inferred behaviour rather than presenting it as a verified code fact.
