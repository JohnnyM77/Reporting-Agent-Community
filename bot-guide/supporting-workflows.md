# Supporting workflows and shared infrastructure

The named agents are only part of the system. This page covers adjacent tasks that feed the dashboard or create deeper research artifacts.

## Results Pack Agent

A workflow for building a fuller pack around a company’s results announcement. It fetches ASX material, detects relevant reports, runs structured analysis, builds a pack and can upload it to Google Drive. It is a separate workflow from Bob’s normal digest path.

- Code: [`results_pack_agent/`](../results_pack_agent)
- Workflow: [`results_pack_agent.yml`](../.github/workflows/results_pack_agent.yml)

## Transcript and podcast workflows

Ned-related workflows can fetch podcast/video transcripts and create summaries or PDFs for later review. These runs are not the same as the daily news scan. See the workflows for [podcasts](../.github/workflows/ned_podcast.yml), [transcripts](../.github/workflows/ned_transcript.yml), and [Ausbiz video](../.github/workflows/ned_ausbiz_video.yml).

## Shared services

- [`shared/llm.py`](../shared/llm.py) — common model-call helpers and retry/batch behaviour.
- [`shared/email_service.py`](../shared/email_service.py) — shared email sending.
- [`shared/asx.py`](../shared/asx.py) and [`shared/asx_simple_fetcher.py`](../shared/asx_simple_fetcher.py) — common ASX retrieval utilities.
- [`shared/gdrive.py`](../shared/gdrive.py) — Google Drive integration.
- [`shared/eodhd.py`](../shared/eodhd.py) — EODHD data integration.
- [`shared/securities.py`](../shared/securities.py) and [`shared/eps_history.py`](../shared/eps_history.py) — shared security/financial-data helpers.
- [`shared/public_safety.py`](../shared/public_safety.py) and [`scripts/leak_guard.py`](../scripts/leak_guard.py) — scrub and guard public outputs.

## Dashboard and publication

Agents write JSON data to files under [`docs/data/`](../docs/data). The dashboard builder combines those sections into the site. The Pages workflow is deliberately the single publisher for the dashboard and Theo slides because deploying separate parts independently could replace the other part of the site.

## Privacy warning

The main repository is private, but its Pages site and the community edition are public. Any new public-facing output must be reviewed for position dollars, share counts, weights and secrets. The repo includes a leak guard; do not bypass it to force a deployment.

## Workflows to know

| Workflow | Role |
|---|---|
| [Daily Announcement Digest](../.github/workflows/daily.yml) | Bob / ASX |
| [Wally Watchlist Screening](../.github/workflows/wally_watchlists.yml) | Wally |
| [Ned News Agent](../.github/workflows/ned_news.yml) | Ned |
| [Harry Hindsight](../.github/workflows/captain_hindsight.yml) | Harry |
| [Selling Sally Weekly Review](../.github/workflows/sunday_sally_weekly_review.yml) | Sally |
| [Sally Wedge Check](../.github/workflows/sally_wedge.yml) | Sally on-demand |
| [Micky’s Macro](../.github/workflows/mickys_macro.yml) | Micky’s Macro |
| [Esther the Wrestler](../.github/workflows/esther.yml) | Esther |
| [Shorty Short Interest](../.github/workflows/shorty_report.yml) | Shorty |
| [Singapore Slinger Daily](../.github/workflows/sgx_daily.yml) | SGX |
| [Bob USA Daily](../.github/workflows/us_daily.yml) | US SEC filings |
| [Publish site](../.github/workflows/theo-pages.yml) | Dashboard and Theo publishing |
