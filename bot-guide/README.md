# Investing bot guide

This guide is maintained against the code and GitHub Actions workflows in this repository.

**For the complete, side-by-side input → processing → prompt/tool → output map, start with [Bot Workflows](../docs/BOT_WORKFLOWS.md).** That document covers the full agent set, current triggers, output paths, and where implementation details are not confirmed.

## Agent pages

- [Bob the Bot — ASX announcements](bob.md)
- [Bob USA and Singapore Slinger — regional filings](regional-agents.md)
- [Wally — watchlist and valuation screening](wally.md)
- [Selling Sally — valuation wedge and sell discipline](sally.md)
- [Harry Hindsight — chief sceptic](harry.md)
- [Ned — news and media](ned.md)
- [Theo — thesis records and review cycles](theo.md)
- [Micky’s Macro — structural-trend research](mickys-macro.md)
- [Shorty — ASIC short interest](shorty.md)
- [Esther the Wrestler — narrative and valuation challenger](esther.md)
- [Supporting workflows and tools](supporting-workflows.md)

## Shared architecture

- [Shared infrastructure](../docs/INFRASTRUCTURE.md)
- [Harry Hindsight architecture](../docs/CAPTAIN_HINDSIGHT_ARCHITECTURE.md)
- [Micky’s Macro architecture](../docs/MICKYS_MACRO_ARCHITECTURE.md)
- [Valuation rules](../docs/VALUATION_RULES.md)

## Accuracy notes

- Workflow YAML is the source of truth for scheduling and manual inputs.
- Python entry points and prompt modules are the source of truth for processing and model instructions.
- A module or directory is not proof that an agent is running. In particular, **Master Engine is currently scaffolding, with no active production workflow invoking it**.
- Harry’s automatic chaining from other agents is disabled in the current workflow; it is available through manual dispatch.
- Keep descriptions of prompts, external APIs and storage tied to code that actually invokes them. Do not infer that an LLM has arbitrary access to a tool merely because the repository has that integration.
