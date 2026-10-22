# Investing agents — end-to-end workflow map

This is the implementation-oriented map of the **current `JohnnyM77/Reporting-Agent` repository**. It is intended to answer four questions for each agent: **what goes in, what happens to it, which prompts/tools are involved, and where the result goes**.

> **How to read this:** workflow YAML is the authority for triggers and runner environment; Python entry points and prompt modules are the authority for processing. A secret listed below is an integration credential, not a tool the model can invoke freely. Where a workflow or code path does not establish a detail, it is labelled “not confirmed” rather than inferred.

## At a glance

| Agent / workflow | Input and source | Processing / prompts | Main tools and integrations | Output / destination | Trigger |
|---|---|---|---|---|---|
| **Bob the Bot (ASX)** | `tickers.yaml`; ASX announcements; PDFs and related releases | Classify event; route to announcement-specific prompt constants in `prompts.py`; deep analysis for selected material types, short summary for routine items | Python; ASX HTTP fetch; Playwright fallback; PDF text extraction; Anthropic via `shared/llm.py` / `shared/pdf_llm.py`; SMTP; Google Drive | Daily email with HIGH IMPACT / MATERIAL / FYI; selected PDFs and analysis in Drive; `docs/data/bob.json`; seen-state cache/file | Daily schedule; manual force-rerun, ticker override, or results-ticker inputs |
| **Bob USA** | `tickers.yaml` `us:` list; SEC EDGAR submissions and 10-K/10-Q/earnings 8-K documents | Select latest results set; classify; analyse results with US-specific results prompt; parse structured JSON | SEC EDGAR HTTP; Playwright/document download; native PDF blocks to Anthropic through shared LLM transport; SMTP | Email + analysis PDF; `docs/data/us.json`; filing accession seen-state | Daily schedule and manual single-ticker / portfolio / dry-run |
| **Singapore Slinger** | `tickers.yaml` `sgx:` list; SGX announcements and PDFs | Fetch and dedupe; classify by SGX categories; deep analysis only for HY/FY results using results prompt; structured metrics, summary and full analysis | Self-hosted Windows/Chrome + Playwright/SGX request replay; PDF retrieval; Anthropic via shared PDF LLM; SMTP | Daily email with three buckets and source links; analysis PDF attachments; `docs/data/slinger.json`; seen-state | Daily at 08:15 SGT; manual ticker/lookback/results/fetch-only/dry-run |
| **Wally** | `watchlists/*.yaml`; optional target prices; valuation config under `valuations/`; market/price history | Screen for near 52-week lows and at/below target prices; collect significant ASX news; build charts and valuation support | EODHD market data; ASX fetcher; Anthropic analyst; Python charting/workbooks; optional Google Drive; SMTP | Combined watchlist email; charts/workbooks and run outputs; `docs/data/wally.json`; fundamentals cache | Weekly Saturday morning SGT; manual run |
| **Selling Sally** | Portfolio and valuation inputs; historical valuation multiples; prices; announcements/news; investment/IRR ledger | Calculate price-versus-value “wedge”; distinguish earnings changes from multiple changes; classify alerts and apply Harry flags; generate memo/report | EODHD; ASX/news fetch; Anthropic analyst; Python charts/workbook/PDF; optional Drive; SMTP | Weekly email and artifacts; `docs/data/sally.json`; on-demand wedge workflow retains artifacts but does not update weekly dashboard JSON or Drive | Weekly Sunday 08:00 SGT; separate manual Sally Wedge Check |
| **Harry Hindsight** | Bob/Wally/Sally/Theo outputs; `data/decisions.json`; `theses/*.md`; portfolio/price context; prior cases | Deterministic gates first; triage and prioritise only meaningful events; thesis test, Seven Powers, Munger tendencies, Annie Duke-style decision/bet review, sell-specific capital/forced-sale tests; bounded model calls | Python gating and validators; Anthropic through `hindsight/llm.py`; web/price helpers where the chosen analysis requires them; PDF/email; Actions cache for memory | Email report/PDF; `docs/data/harry.json` and thesis summary data; private-to-runner cached `hindsight_data/` case store by default | Manual dispatch modes: daily, sell, sweep, portfolio, autopsy, scorecard. Automatic chaining from other agents is currently disabled in workflow comments. |
| **Ned** | `media_sources.yaml`; portfolio `tickers.yaml`; company aliases; RSS/Google News/Yahoo Finance; YouTube; configured newsletters via read-only IMAP | Resolve entities; dedupe; score source quality and importance; summarize selected items; low-quality rewrite mills are capped and not individually LLM-summarised | RSS/HTTP; YouTube Data API; transcript libraries; Anthropic summaries; OpenAI Whisper for audio/video transcript workflows; IMAP read-only; SMTP; PDF/render tools | Daily email; `docs/data/ned.json`; transcript index `docs/data/transcripts.json`; PDF/artifact outputs | News scan daily 07:30 SGT; separate manual YouTube/podcast/AusBiz transcript workflows and source probe |
| **Theo** | `theses/*.md`; `data/decisions.json`; agent dashboard JSON; quality configs | Validate thesis structure; render thesis pages/slides; calculate drift/signals; generate pre-results season pack and review-cycle prompts | Python CLI/templates; YAML/JSON; Jinja2; OpenPyXL; GitHub Pages | Thesis views/slides, season-pack email/text output; combined public dashboard/site | Pages publish on relevant pushes and selected agent completions; season pack 1 Jan and 1 Jul UTC; CLI/manual use |
| **Micky’s Macro** | Priority research emails in configured Gmail inbox, read through read-only IMAP; source registry and trend taxonomy | One structured extraction call per new email; separate author claims from system inference; map claims to trends and company candidates; score dossiers and portfolio/watchlist overlap | IMAP; Anthropic via shared LLM transport; Python/Pydantic; Wally adapter; web helpers; PDF renderer; SMTP; Actions cache | Weekly Macro Investment Review email/PDF; public-safe `docs/data/mickys_macro.json`; detailed dossiers in gitignored cached `mickys_macro_data/` | Weekly Sunday 08:00 SGT; manual incremental/backfill/daily/weekly and no-email modes |
| **Shorty** | ASIC short-position reports; ASX portfolio from `tickers.yaml`; Wally watchlists; ETFs excluded from portfolio universe | Find latest available report and FY-start baseline; compare reported short percentage and market-wide rank; curate most-shorted names and biggest movers | HTTP requests + Playwright; Python calculations; PDF rendering; SMTP; dashboard JSON | Weekly email with PDF detail; `docs/data/shorty.json` for portfolio holdings (watchlist breakdown is in email/PDF) | Weekly Sunday 08:00 SGT; manual date/baseline override and dry-run |
| **Esther the Wrestler** | User-selected ticker(s), mode, optional notes, price overrides and ASX PDF URLs; existing Bob/Wally/Sally/Harry/Theo outputs; latest disclosures | One company-level structured JSON analysis; modes full, quick, valuation, thesis, challenge; QC and one repair retry on hard failure | Anthropic (default model `claude-opus-4-6`); disclosure/web research in model call; requests/PDF parsing/pandas; SMTP; optional private repo for prior-run comparison | Email report; prior-run comparison only persists when optional private-store token is configured; main repo is read-only | Manual dispatch only |
| **Mike Stock Quality** | Chosen sample list or portfolio, optional ticker override; EODHD statutory statements; optional market-position evidence | Score quantitative quality criteria as specified in Mike framework; optional one Claude call/company for Market Position evidence; QA/QC PASS or DRAFT | EODHD API; Anthropic (configurable model, default `claude-sonnet-4-6`) with web search for evidence; PDF render; SMTP | PDF report and optional email; run files under `outputs/mike/run`; no dashboard publish or repo commit | Manual dispatch only |
| **Results Pack Agent** | Required ASX ticker; optional HY/FY type, date preference, upload/valuation/Strawman/dry-run/force options | Find result-day pack and related disclosures; download PDFs; run result prompts; assemble output pack; optionally build valuation workbook and Strawman draft | ASX announcement retrieval; requests/BeautifulSoup/Playwright; pypdf; Anthropic; Google Drive API; OpenPyXL/XlsxWriter | `outputs/` result pack, metadata/PDFs; optional Google Drive upload, valuation workbook and Strawman draft | Manual dispatch only |
| **Master Engine** | Event schema and agent events in `shared/events.py`; aggregator modules under `master_engine/` | Aggregation, linking, prioritisation and rendering components exist | Python modules only; no current production workflow | No scheduled/production output currently confirmed | **Not running:** no active workflow invokes it |
| **EODHD / archetype maintenance** | EODHD API and configured ticker/archetype data | API check and/or sync/review of archetype configuration | EODHD API; Python scripts/workflows | Diagnostic output or config/report artifacts | Supporting maintenance workflows, not portfolio intelligence digests |

## Detailed workflow cards

The following cards use the same order as the requested visual: **input → fetch/validate → classify and analyse → output**.

### 1. Bob the Bot — ASX announcements

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Scheduled/manual GitHub Actions run reads the ASX portfolio in `tickers.yaml`. Manual inputs can force selected tickers, analyse non-portfolio tickers, or request the last HY/FY result set. |
| **2 · Fetch & validate** | Fetch ASX announcement listings; apply the lookback window and seen-ID deduplication; retrieve important PDFs by direct HTTP, falling back to Playwright when needed; extract PDF text and reject empty/boilerplate/broken documents. |
| **3 · Classify, prompt & analyse** | `agent.py` routes to prompt constants in `prompts.py`: `RESULTS_HYFY_PROMPT`, `ACQUISITION_PROMPT`, `FUNDRAISE_PROMPT`, `REMUNERATION_PROMPT`, `TRADING_UPDATE_PROMPT`, `QUARTERLY_4C_PROMPT`, `PRICE_SENSITIVE_PROMPT`, or `DEFAULT_2LINE_PROMPT`. Structured analysis is requested for deep-analysis categories; routine items get a short summary. |
| **4 · Report & deliver** | Email separates HIGH IMPACT, MATERIAL and FYI; includes source links and quick metrics/summary; selected detailed analysis and source documents are saved to Drive; dashboard card written to `docs/data/bob.json`. |

**Core files:** `agent.py`, `asx_fetch.py`, `playwright_fetch.py`, `prompts.py`, `shared/llm.py`, `shared/pdf_llm.py`, `shared/email_service.py`, `shared/gdrive.py`, `.github/workflows/daily.yml`.

### 2. Bob USA — SEC filings

| Stage | What the implementation does |
|---|---|
| **1 · Input** | `tickers.yaml` `us:` section; manual ticker or full-portfolio selection. |
| **2 · Fetch & validate** | Resolve ticker to SEC CIK; retrieve SEC submissions; select latest 10-K/10-Q plus matching earnings 8-K (if present); download and render relevant documents. |
| **3 · Prompt & analyse** | Uses the US results-analysis prompt `RESULTS_HYFY_PROMPT_US` and structured JSON output with metrics, summary and full analysis. |
| **4 · Report & deliver** | Email with attached analysis PDF; update `docs/data/us.json`; accession-based seen-state prevents repeating the same filing. |

**Core files:** `us_agent.py`, `us_fetch.py`, `us_docs.py`, `us_classify.py`, `prompts.py`, `.github/workflows/us_daily.yml`.

### 3. Singapore Slinger — SGX announcements

| Stage | What the implementation does |
|---|---|
| **1 · Input** | `tickers.yaml` `sgx:` section or manual ticker override; lookback-hours and optional last-results request. |
| **2 · Fetch & validate** | Self-hosted Windows/Chrome runner primes the SGX browser flow and replays the authorised request; filter by lookback and dedupe with SGX-specific seen-state; fetch PDFs. |
| **3 · Prompt & analyse** | Classifies by SGX category. Deep analysis is limited to `RESULTS_HY_FY`, using the structured results prompt through shared PDF/LLM transport. |
| **4 · Report & deliver** | Three-bucket email with source links and metrics card; analysis PDFs attached; dashboard data written to `docs/data/slinger.json`. Fetch-only and dry-run modes are available. |

**Core files:** `sgx_agent.py`, `sgx_fetch.py`, `sgx_classify.py`, `sgx_pdf.py`, `sgx_email.py`, `.github/workflows/sgx_daily.yml`.

### 4. Wally — watchlist screen

| Stage | What the implementation does |
|---|---|
| **1 · Input** | YAML watchlists under `watchlists/`, optional target prices, and valuation configs in `valuations/`. |
| **2 · Fetch & validate** | Retrieve current prices, 52-week range, historical closes and valuation/fundamental inputs; normalise ticker/target formats. |
| **3 · Screen & enrich** | Flag a ticker within 5% of its 52-week low or at/below its configured target price; collect significant ASX news; build value/range charts and optional valuation workbooks. Anthropic analysis is used for configured analyst/news tasks, not as the screening rule itself. |
| **4 · Report & deliver** | One combined email for the watchlists; dashboard output `docs/data/wally.json`; run artifacts/cache and optional Drive uploads. |

**Core files:** `wally/main.py`, `wally/watchlist_loader.py`, `wally/data_fetch.py`, `wally/screening.py`, `wally/claude_analyst.py`, `wally/charts.py`, `.github/workflows/wally_watchlists.yml`.

### 5. Selling Sally — weekly valuation review and wedge

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Portfolio, per-ticker valuation settings, historical valuation data, price data and IRR/decision ledger. |
| **2 · Fetch & validate** | Load prices and fundamentals; fetch relevant ASX/news context; read past valuation multiples from git history for the wedge. |
| **3 · Calculate & analyse** | Compute price-versus-value range; analyse whether the price move is associated with earnings or multiple change; classify alerts, add configured Harry flags, and write a company memo/report. |
| **4 · Report & deliver** | Weekly email, charts/workbook/PDF and `docs/data/sally.json`; separate manual Sally Wedge Check does not update that dashboard JSON or upload to Drive. |

**Core files:** `sunday-sally/src/main.py`, `value_wedge.py`, `valuation_engine.py`, `historical_multiple_analyzer.py`, `alert_engine.py`, `memo_generator.py`, `.github/workflows/sunday_sally_weekly_review.yml`, `.github/workflows/sally_wedge.yml`.

### 6. Harry Hindsight — chief sceptic

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Existing Bob/Sally/Wally/Theo output; `data/decisions.json`; thesis files; portfolio and price context; prior case history. |
| **2 · Gate & validate** | Collect candidate events, apply deterministic gates, dedupe/triage and rank by priority before paying for model calls. |
| **3 · Challenge** | Runs thesis-change tests, Seven Powers (`hindsight/frameworks/seven_powers.yaml`), Munger tendencies, Annie Duke-style decision/bet framing, and sell-specific fresh-capital/forced-sale tests where relevant. Prompt templates live in `hindsight/prompts.py`. |
| **4 · Report & memory** | Email and PDF; `docs/data/harry.json` and thesis-related public-safe output; detailed cases/profile in gitignored `hindsight_data/`, persisted between runs via Actions cache by default. |

**Current trigger caveat:** `.github/workflows/captain_hindsight.yml` says automatic chaining from Bob/Wally/Sally was disabled. Use manual dispatch for `daily`, `sell`, `sweep`, `portfolio`, `autopsy`, or `scorecard`.

### 7. Ned — news and media

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Source registry `media_sources.yaml`, ticker/company aliases, configured RSS feeds, Google News, Yahoo Finance, YouTube channels and newsletter inbox. |
| **2 · Fetch & resolve** | Scan RSS/news sources; resolve company names/tickers; newsletter workflow reads mail using read-only IMAP; separate workflows accept podcast, YouTube or video URLs. |
| **3 · Score & summarise** | Deduplicate, apply source-quality tiers and importance scoring; Anthropic summarises selected hits. Low-quality rewrite-mill sources are capped at low importance and skip individual LLM summaries. Podcast/video workflows can use OpenAI Whisper for transcription before the same digest path. |
| **4 · Report & publish** | Daily email and `docs/data/ned.json`; transcript index `docs/data/transcripts.json`; transcript PDFs/artifacts; dashboard build/publish follows the applicable workflow. |

**Core files:** `ned/main.py`, `news_scanner.py`, `newsletter_scanner.py`, `youtube_scanner.py`, `podcast_transcript_fetcher.py`, `source_quality.py`, `importance_scorer.py`, `email_builder.py`; `ned_news.yml`, `ned_podcast.yml`, `ned_transcript.yml`, `ned_ausbiz_video.yml`.

### 8. Theo — thesis system and publishing

| Stage | What the implementation does |
|---|---|
| **1 · Input** | `theses/*.md`, `data/decisions.json`, agent JSON, business/decision-quality configs. |
| **2 · Validate** | Checks thesis structure; malformed thesis data can stop publication rather than render incomplete content. |
| **3 · Render & review** | CLI supports thesis rendering, drift checks, signals, review cycles and seasonal pre-results packs. Sally signals can inform review questions. |
| **4 · Publish** | One Pages workflow builds dashboard and Theo pages together. The seasonal pack is emailed; public output passes through public-safety checks. |

**Core files:** `theo/cli.py`, `theo/thesis.py`, `theo/drift.py`, `theo/signals.py`, `theo/season.py`, `theo/publish.py`, `.github/workflows/theo-pages.yml`, `.github/workflows/theo-season.yml`.

### 9. Micky’s Macro — structural-trend research

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Configured priority Gmail research/newsletter sources, read-only over IMAP; source registry and trend taxonomy. |
| **2 · Ingest & validate** | Deduplicate email by Message-ID; extract content; keep source claims distinct from the agent’s own inferences. |
| **3 · Extract & map** | Structured Claude extraction per new email; map claims to trend dossiers and company candidates; score dossiers and calculate portfolio/watchlist overlap via Wally adapter. |
| **4 · Report & store** | Weekly review email/PDF and public-safe dashboard JSON; detailed research store is gitignored and cached across workflow runs. |

**Core files:** `mickys_macro/main.py`, `gmail_ingest.py`, `claim_extraction.py`, `trend_mapping.py`, `company_mapping.py`, `scoring.py`, `portfolio_overlap.py`, `config/macro_sources.yaml`, `config/macro_taxonomy.yaml`, `.github/workflows/mickys_macro.yml`.

### 10. Shorty — ASIC short interest

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Latest available ASIC report; financial-year-start baseline; portfolio tickers and Wally watchlists. |
| **2 · Fetch & compare** | Probe backward for latest report and around 1 July for baseline; compare short percentage of shares on issue and market-wide ranking. |
| **3 · Curate** | Calculate biggest changes and most-shorted names; no LLM call and no seen-state dedupe (it is a periodic numerical report). |
| **4 · Report & publish** | Email summary plus detailed PDF; dashboard `docs/data/shorty.json` contains portfolio holdings, while watchlist detail stays in email/PDF. |

**Core files:** `shorty_agent.py`, `shorty_fetch.py`, `shorty_pdf.py`, `shorty_email.py`, `.github/workflows/shorty_report.yml`.

### 11. Esther — narrative and valuation editor

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Manual ticker list, mode, optional notes, price overrides and source PDF URLs. |
| **2 · Context** | Reads existing agent output and builds company/valuation context; researches recent disclosures using the configured model’s web research capability. |
| **3 · Analyse & QC** | `esther/prompts.py` defines the system prompt; a company-level response is expected as strict JSON. Hard QC failures get one repair retry; API/invalid failures remain visibly distinct. Modes: full, quick, valuation, thesis, challenge. |
| **4 · Report & history** | Emails the result. The main repo is read-only. Prior-run history persists only when the optional private store token is configured. |

**Core files:** `esther/main.py`, `context.py`, `analyst.py`, `prompts.py`, `valuation.py`, `quality.py`, `.github/workflows/esther.yml`.

### 12. Mike — stock quality framework

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Manual selection of `mikebrisy_sample` or portfolio, or explicit tickers. |
| **2 · Data** | EODHD statutory financial statements feed the quantitative criteria. |
| **3 · Evidence & scoring** | The framework scores the quantitative criteria as written; optional Claude web-search call/company supplies the Market Position evidence register and permitted overlays; QA/QC returns PASS or DRAFT. |
| **4 · Report** | PDF report and optional email. Writes run output under `outputs/mike/run`; workflow is read-only and does not publish dashboard JSON or commit outputs. |

**Core files:** `mike/`, `config/mike.yaml`, `.github/workflows/mike.yml`.

### 13. Results Pack Agent — one-off results bundle

| Stage | What the implementation does |
|---|---|
| **1 · Input** | Manual ASX ticker; optional HY/FY type and date; toggles for Drive upload, valuation workbook, Strawman draft, dry-run, force and recent-date listing. |
| **2 · Find & download** | Find likely result-day pack and associated announcements; download PDFs and record metadata. |
| **3 · Analyse & assemble** | Runs result prompt(s) in `results_pack_agent/prompts.py`; builds a consolidated pack. Optional valuation runner creates a Wally-style valuation workbook. |
| **4 · Deliver** | Saves bundle under `outputs/`; optionally uploads to Drive and includes a Strawman.com post draft. This is a manual tool, not a scheduled daily bot. |

**Core files:** `results_pack_agent/main.py`, `asx_fetcher.py`, `pack_builder.py`, `pdf_downloader.py`, `claude_runner.py`, `prompts.py`, `valuation_runner.py`, `.github/workflows/results_pack_agent.yml`.

## Shared services and cross-cutting rules

| Shared component | Role |
|---|---|
| `shared/llm.py` | Shared LLM transport used by several agents; the model is invoked by application code with a defined prompt, not given arbitrary access to all integrations. |
| `shared/pdf_llm.py` | PDF-aware analysis transport for filing/report workflows. |
| `shared/email_service.py` / `shared/email_html.py` | Email delivery and reusable email formatting. |
| `shared/asx.py`, `shared/asx_simple_fetcher.py`, `asx_fetch.py`, `playwright_fetch.py` | ASX announcement retrieval and fallback paths. |
| `shared/gdrive.py` | Google Drive integration for agents that upload selected documents. |
| `shared/eodhd.py`, `shared/eps_history.py`, `shared/ranges.py`, `shared/lows.py` | Market data and common calculations. |
| `shared/events.py` | Shared investor-event schema; not proof that a live Master Engine consumes the events. |
| `shared/public_safety.py`, `scripts/leak_guard.py` | Controls intended to keep private data out of public dashboard/site output. |
| `scripts/build_dashboard.py` and `dashboard/` | Assemble agent JSON into the dashboard; the single Pages publisher deploys the dashboard and Theo pages together. |

## Operational and security notes

- GitHub Actions workflows define the actual schedule. Cron expressions are UTC and comments explain intended local time; daylight saving can affect displayed local times.
- Credentials are expected in GitHub Secrets or repository variables. Never put API keys, email credentials, private case files or personal portfolio notes into committed public-safe JSON.
- Some agent stores are deliberately gitignored and carried between runs with GitHub Actions cache; a cache is persistence, not a guaranteed archival database.
- A scheduled workflow is not proof that every run succeeded. Check the Actions run, logs and current dashboard JSON.
- “Uses Claude/web search” means the app invokes the configured Anthropic model or search capability in code. It does **not** mean the model can freely call every API or tool available in a developer environment.
- Master Engine modules exist, but this repository currently has no production workflow invoking them. Treat it as non-running until a workflow or other deployment is added.
