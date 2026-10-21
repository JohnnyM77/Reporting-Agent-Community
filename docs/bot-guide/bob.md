# Bob the Bot

**Job:** read the announcements so I do not have to read every announcement myself.

Bob is the portfolio announcement-monitoring and triage agent. Its main entry point is `agent.py`, with announcement retrieval helpers and shared services under `shared/`.

## What Bob does

1. Reads the configured security universe from `tickers.yaml`.
2. Retrieves recent ASX announcements and works within a configurable look-back window (the current code defines `HOURS_BACK = 24`).
3. Deduplicates previously seen announcement IDs using `state_seen.json`. The documented retention period is 72 hours.
4. Classifies announcements and routes them by materiality.
5. Retrieves documents for important announcements, using direct HTTP first and Playwright/browser fallback where needed.
6. Extracts document text and runs the appropriate analysis prompt.
7. Produces the email digest and writes a machine-readable dashboard payload.

## The three digest buckets

- **HIGH IMPACT:** events selected for deeper analysis, such as results, acquisitions and capital or debt raises.
- **MATERIAL:** announcements that deserve attention but do not necessarily need the full deep-analysis path.
- **FYI:** lower-impact items, retained as a quick headline/summary and source link rather than silently disappearing.

The exact routing rules live in `agent.py` and the prompt constants in `prompts.py`. Do not assume every item in HIGH IMPACT is a buy or sell signal. Bob reports and interprets disclosure; it does not own the portfolio decision.

## What comes out

- Daily email digest with source links.
- Detailed analysis and, for selected reports, supporting PDFs.
- Important documents uploaded to Google Drive where the workflow and credentials allow it.
- Dashboard data at `docs/data/bob.json`.
- Internal event output can be built by `bob_emit.py` for the shared event schema.

## Key files

- [`agent.py`](../../agent.py): orchestration and routing.
- [`prompts.py`](../../prompts.py): analysis instructions, including results, 4C/5B, acquisitions, fundraising, remuneration, trading updates and price-sensitive announcements.
- [`tickers.yaml`](../../tickers.yaml): monitored securities by exchange.
- [`asx_fetch.py`](../../asx_fetch.py) and [`playwright_fetch.py`](../../playwright_fetch.py): retrieval.
- [`shared/llm.py`](../../shared/llm.py), [`shared/pdf_llm.py`](../../shared/pdf_llm.py): model transport and PDF handling.
- [`shared/email_service.py`](../../shared/email_service.py): email delivery.
- [` .github/workflows/daily.yml`](../../.github/workflows/daily.yml): scheduled run.

## Guardrails and limitations

- Previously processed announcements are skipped unless the supported force-rerun option is used.
- Per-run announcement, PDF and model-call caps limit runaway work.
- PDF retrieval can fail, and some announcements do not contain enough evidence for a full analysis. A short or failed analysis is not proof that the event is unimportant.
- Bob's output is a research input, not an instruction to trade. Check the source announcement for material decisions.

## In one sentence

Bob is the **disclosure radar**: he finds what changed, tells me why it may matter, and points me to the original evidence.
