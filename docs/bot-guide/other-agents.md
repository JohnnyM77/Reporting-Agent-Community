# The other agents

This page covers the supporting agents described by the repository's infrastructure map. Their presence in the codebase is not, by itself, proof that every external service or scheduled run is currently healthy.

## Bob USA

**Job:** check US holdings for company filings and results-related developments.

- Entry point: `us_agent.py`
- Fetching: `us_fetch.py` and `us_docs.py`, using SEC-related sources.
- Configured universe: the `us` section of `tickers.yaml`.
- Dashboard output: `docs/data/us.json`.
- Workflow: `us_daily.yml` supports on-demand single-ticker dispatches; the infrastructure map also says the main daily workflow runs the US check after the ASX Bob cycle.

This is the US-filing counterpart to Bob's ASX announcement monitor. Do not assume it has the same source coverage or analysis prompts as the ASX workflow.

## Slinger

**Job:** monitor SGX-listed securities for announcements.

- Entry point: `sgx_agent.py`.
- Fetching and PDF handling: `sgx_fetch.py` and `sgx_pdf.py`.
- Configured universe: the `sgx` section of `tickers.yaml`.
- Dashboard output: `docs/data/slinger.json`.
- Workflow: `sgx_daily.yml`, documented as using a self-hosted Windows runner.

The self-hosted runner is a real dependency, not a cosmetic detail. If that machine or its runner service is unavailable, the workflow may not execute.

## Ned

**Job:** gather news and podcast/transcript context, rather than retrieve primary company filings.

- Code area: `ned/`.
- Entry point: `python -m ned.main`.
- Inputs: RSS, YouTube and Yahoo news search, with headlines used for news scanning rather than treating search snippets as reliable financial figures.
- Outputs: `docs/data/ned.json` and transcript data.
- Workflows listed in the infrastructure map: `ned_news.yml`, `ned_podcast.yml`, and a self-hosted `ned_transcript.yml`.

Ned is useful for context and discovery. For a price-sensitive claim, follow the trail back to the original announcement, filing or full transcript.

## Theo

**Job:** keep the written investment thesis structured, versioned and reviewable.

- Code area: `theo/`, with thesis files under `theses/*.md`.
- Workflow: `theo-season.yml` runs the season review; `theo-pages.yml` publishes the thesis site/dashboard.
- Inputs and signals: structured thesis pillars, kill conditions, reviews and amendments, plus signals from Sally and Harry.
- Output: updated thesis records and a published view. Harry reads the theses and their Git history; it does not write changes to them.

Theo is the memory of *why I own a company*. The useful question is not merely whether the share price has fallen, but whether the evidence has weakened a thesis pillar or triggered a kill condition.

## Results Pack

**Job:** retrieve and analyse results documents as a focused workflow.

- Entry point: `python -m results_pack_agent.main`.
- Retrieval: `shared/asx_simple_fetcher.py` and `shared.asx`.
- Model and PDF support: `shared.llm` and `shared.pdf_llm`.
- Workflow: `results_pack_agent.yml`.
- Output: `outputs/`.

The infrastructure map says this agent does not send email directly. Its value is in assembling and analysing the results pack; the exact current report contents should be checked against the implementation and prompt before relying on any specific field.

## Micky's Macro and Shorty

I could not verify either name as an implemented agent in the inspected repository documentation or infrastructure map. They may live in a different repository, workflow, or external service. This guide deliberately does not guess their jobs. Add their source repository and entry point before documenting their triggers, inputs or outputs.
