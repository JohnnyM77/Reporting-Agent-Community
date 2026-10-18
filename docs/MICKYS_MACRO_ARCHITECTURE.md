# Micky's Macro: architecture and implementation plan

Micky's Macro is the structural-trends / macro research agent: it reads
research newsletters, maps the macro forces they describe through to
investable companies, scores the trends transparently, and hands qualified
candidates to the agents that already own portfolio and watchlist data. It
never buys, sells, or resizes anything, and it never writes into another
agent's files.

The brief that commissioned this (see the PR description / task body) names
it "Micky's Macro" throughout the spec text but titles the request "Micky's
Macro" once. The code, config, module and files below all use **Mark's
Macro** / `mickys_macro`, since that is what the spec itself calls the thing
in every section but the title. Say the word if the name should change —
it is a `sed` away.

## 1. What exists (verified by reading the code, 2026-10-18)

There is no "Bob the Boss", "Thesis" agent, "Provocateur" or "JM-Investor"
agent in the codebase under those names — those are Johnny's own names for
roles, not literal modules. Mapping them onto what is actually here:

| Spec's name | What it actually is |
|---|---|
| Bob the Bot / Bob the Boss | **Bob** (`agent.py`), ASX announcement digest. Monitors `tickers.yaml`'s `asx:` (+ `lse`/`sgx`/`us` siblings run by Slinger/US Bob), writes `docs/data/bob.json`. |
| Wally | **Wally the Watcher** (`wally/`), watchlist screening for near-lows / below-buy-price, writes `docs/data/wally.json`. Watchlists live in `watchlists/*.yaml`, loaded by `wally/watchlist_loader.py`, de-duplicated across five standard lists in `wally/config.py::STANDARD_WATCHLISTS`. |
| Sally | **Selling Sally** (`sunday-sally/`), the value-wedge sell discipline, writes `docs/data/sally.json`. |
| Thesis | Not an agent — **`theses/*.md`**, one frontmatter+markdown file per holding, read by Theo (who publishes slide decks from them) and Harry (who re-scores them each sweep and records changes in `docs/data/harry_theses.json`). |
| The Provocateur | **Harry Hindsight** (`hindsight/`), "the Chief Sceptic" — reads Bob/Sally/Wally/Theo's outputs through read-only adapters, never imports or modifies them, flags broken theses to Sally via `data/harry_flags.yaml`. This is the closest existing analogue to "Provocateur", and Micky's Macro is built on the same pattern. |
| JM-Investor | No standalone module; closest matches are the `jm_watchlist.yaml` list and the `anthropic-skills:jm-investor` Claude Code skill (Johnny's personal ASX analysis framework, used interactively, not a scheduled agent). |

Esther (`esther/`) is the other agent built on Harry's pattern (reads
Bob/Wally/Sally/Harry/theses, never writes them, private local store). Mark's
Macro follows the same shape a third time.

### 1.1 Portfolio / watchlist / company-research data already in the repo

- `tickers.yaml` — canonical ticker universe (`asx`, `lse`, `sgx`, `us`), ETFs
  marked in `etf_tickers`. Read, never written, by every agent.
- `watchlists/*.yaml` — five standard watchlists + `tii75_watchlist.yaml`,
  loaded via `wally/watchlist_loader.py` (ticker + optional `target_price`).
- `data/decisions.json` — the money-free IRR ledger export (dates/actions,
  no dollar figures) Theo and Hindsight read for holding dates.
- `theses/*.md` — one frontmatter+markdown file per holding (ticker, status,
  conviction, sources, the bet, kill condition). Owned by Theo.
- `config/ticker_archetypes.yaml` / `config/valuation_archetypes.yaml` — buy
  multiples by business archetype (`shared/classifier.py`), never hard-coded
  per agent.
- `docs/data/{bob,wally,sally,harry,harry_theses,shorty,slinger,ned,theo,us}.json`
  — every agent's latest run, public-safe, feeding the dashboard.

### 1.2 Announcement ingestion / financial analysis / reporting workflows

- ASX: `agent.py` + `asx_fetch.py`. SGX: `sgx_*.py`. US: `us_*.py`. All three
  follow the same classify → fetch PDF → one structured LLM call → email →
  dashboard shape (see CLAUDE.md's Bob/Slinger sections).
- `shared/llm.py` — the one Anthropic transport (streaming over 8192 output
  tokens, prompt caching, retry helper). Every agent's model calls go
  through `send()`.
- `shared/email_service.py` — the one SMTP transport. Table-only,
  inline-styled HTML is a hard convention (tested in several agents) because
  Gmail/Outlook strip `<style>` and mishandle flex/grid.
- `shared/eodhd.py` — the only market-data source. No fallback: a figure
  EODHD doesn't have renders `n/a`, never estimated.
- `scripts/build_dashboard.py` + `dashboard/sections/*.py` + `dashboard/page.py`
  — one `_load()` + one line in `sections = [...]` per agent.

### 1.3 Scheduling, logging, config, notifications

- `.github/workflows/*.yml`, one workflow per agent family, `workflow_dispatch`
  plus a cron. `theo-pages.yml` republishes the site on `workflow_run`
  completion of any agent workflow that writes `docs/data/*.json`.
- Agents that keep personal/private state (Harry, Esther) use a local
  gitignored store (`hindsight_data/`, `esther_data/`) carried between runs
  via `actions/cache`, never committed. `hindsight/store.py`'s
  `open_store()` refuses a directory the public repo would track.
- Config is YAML in `config/*.yaml` with env-var overrides read in each
  agent's `config.py` (see `hindsight/config.py` for the pattern).

### 1.4 Gmail authentication / connector capabilities

Two different things exist, and Micky's Macro uses the first:

1. **IMAP app password**, read-only (`imaplib`, `readonly=True`, stdlib
   only) — `ned/newsletter_scanner.py`. No Google Cloud project, no OAuth
   consent screen, no refresh token. Env: `NED_IMAP_USER` /
   `NED_IMAP_PASSWORD`, falling back to `EMAIL_FROM` / `EMAIL_APP_PASSWORD`
   (the same Gmail address/app-password every agent already sends mail
   from). This is the established "Gmail API integration" for *reading*
   mail in this repo — there is no OAuth Gmail-read path.
2. **OAuth2 user credentials for Google Drive** (`shared/gdrive.py`,
   `GDRIVE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN`) — Bob's Drive doc upload.
   Unrelated to reading Gmail.

This session also has a live Gmail MCP connector (read/write tools) attached
to the interactive Claude Code session itself — useful here for *discovering*
the real sender addresses the spec requires ("do not invent sender
addresses"), but it is not something the scheduled GitHub Actions workflow
has access to. The production ingestion path is IMAP, matching Ned's.

### 1.5 Real senders discovered (via the session's Gmail connector, 2026-10-18)

Searched the connected mailbox (`johnmyerscough13@gmail.com`) by name/domain
for each of the four priority sources. These are real senders seen in actual
mail, not invented, and seed `config/macro_sources.yaml`:

| Source | Confirmed sender address(es) |
|---|---|
| Citrini Research | `citrini@substack.com` |
| Ray Dalio / Principled Perspectives | `raydalio@substack.com`, `no-reply@principles.com` (same content, mirrored to two inboxes) |
| Scott Galloway / Prof G | `profgmedia@substack.com`, and sub-newsletter aliases `profgmedia+prof-g@substack.com`, `profgmedia+no-mercy-no-malice@substack.com`, `profgmedia+extra-credit@substack.com` |
| Chamath Palihapitiya | `chamath@substack.com` (earlier), `chamath@mail.beehiiv.com` (current — he moved platforms) |

Generic `no-reply@substack.com` "X posted new notes" cross-promotion emails
are not research and are excluded by rule, not by sender.

## 2. Integration without duplication

- **Reuses, does not fork:** `shared/llm.py`, `shared/email_service.py`,
  `shared/eodhd.py`, `shared/classifier.py` (buy-multiple archetypes),
  `shared/public_safety.py` (public-site scrubbing). No new SMTP, no new
  Anthropic client, no new market-data source, no hard-coded multiple.
- **Storage pattern copied from Harry/Esther**, not from Bob: a local
  gitignored SQLite+files store (`mickys_macro_data/`) for research content
  (claims, extracted theses from private newsletters) that must not be
  committed to a public repo, carried between runs via `actions/cache`.
  `docs/data/mickys_macro.json` carries only the public-safe summary
  (trend names/scores/rationale, candidate tickers, portfolio-overlap
  percentages) — same split Harry uses for `harry_theses.json` vs the
  private store.
- **Adapter pattern copied from `hindsight/adapters.py`:** Micky's Macro reads
  `tickers.yaml`, `watchlists/*.yaml`, `docs/data/{bob,wally,sally}.json`
  read-only to compute portfolio/watchlist overlap. It never imports Bob,
  Wally or Sally's modules and never writes their files.
- **Wally hand-off is a proposal, not a merge.** The spec says Wally
  "receives qualified candidates ... using the existing watchlist
  conventions" but also "do not create competing versions of ... watchlists"
  and, where no integration exists, "create a clearly documented adapter or
  proposal instead of silently changing another bot." Auto-editing
  `wally/config.py::STANDARD_WATCHLISTS` or any of the five standard lists
  would silently change what Wally screens and emails every day without
  Johnny's say. Instead `mickys_macro/wally_adapter.py` writes
  `watchlists/macro_candidates_proposed.yaml` in the exact schema
  `wally/watchlist_loader.py` already reads (ticker + optional
  `target_price` + a `note`), but it is **not** in `STANDARD_WATCHLISTS` —
  nothing screens it automatically. Folding it in (or not) is Johnny's call;
  the Daily/Weekly brief says when new candidates are waiting there.
- **Bob/Sally/Theo hand-offs are documentation + the overlap check for
  now, not code changes to those agents.** Wiring a new ticker into Bob's
  announcement monitoring means adding it to `tickers.yaml`, which changes
  what Bob/Shorty/every ticker-driven agent watches and emails about —
  not something to do silently from a macro-research pass. Likewise feeding
  Harry/Sally new macro context is explicitly called out in CLAUDE.md as "a
  later pass" for the capital/debt-raise work and isn't wired here. These
  are flagged as **decisions needing Johnny's approval**, not implemented.

## 3. Data model (`mickys_macro/schemas.py`)

Pydantic models, same style as `hindsight/schemas.py`:

- `EmailRecord` — sender, publication, subject, received timestamp, Gmail
  message-id/thread-id (dedup key), Gmail link, article links found in the
  body, raw text (store only, never in `docs/data`).
- `ExtractedClaim` — one claim/forecast/hypothesis pulled from a source:
  text, claim type (`FACT` / `FORECAST` / `OPINION` / `INFERENCE` — Mark's
  Macro's own inference is always tagged `INFERENCE` and never presented as
  the author's claim), named companies/industries/commodities/
  countries/technologies, time horizon, supporting evidence, counter-evidence,
  confidence, source ref (email message-id + article URL).
- `TrendDossier` — the 15-field record from the brief (thesis, duration,
  demand drivers, supply constraints, capex, policy dependencies, winners/
  losers, first/second/third-order consequences, evidence for/against,
  invalidation criteria, leading indicators, linked companies, sources,
  confidence, last-reviewed). One row per trend, updated in place as new
  claims arrive — never duplicated.
- `TrendScore` — the ten 1-10 dimensions from section 9 of the brief, each
  with its own rationale/evidence/uncertainty string. No combined score is
  ever computed; `scoring.py` exposes the vector, not an average.
- `CompanyCandidate` — ticker, exchange, currency, exposure type
  (`DIRECT_BENEFICIARY` / `BOTTLENECK_SUPPLIER` / `ENABLER` /
  `POTENTIAL_LOSER`), the macro→company causal chain, valuation snapshot
  (from `shared/eodhd.py`, `None`/`"not covered"` where EODHD has no
  figure — never estimated), portfolio/watchlist overlap, and the four
  filter sections (macro attractiveness / industry economics / company
  quality / valuation) each left as **explicit text fields a human
  (or a later Sally/Harry-style deterministic check) fills in**, not a
  single combined "buy" flag — the brief is explicit that "attractive
  macro trend", "attractive industry", "attractive company" and
  "attractive investment at today's price" are four different
  conclusions, and collapsing them into one score would be exactly the
  kind of misleadingly precise number section 9 forbids.

## 4. What is implemented vs. what needs Johnny's decision

Implemented and runnable end-to-end in this PR: Gmail IMAP ingestion with
dedup, claim extraction (one structured Claude call per new email, same
JSON-repair-on-failure discipline as Bob/Slinger), the trend taxonomy and
dossier store, the 10-dimension scorecard, company candidate mapping with
real EODHD valuation data (never fabricated), portfolio/watchlist overlap,
the Daily Macro Brief and Weekly Macro Investment Review emails, the Gmail
Research Digest, Company Opportunity Briefs, the Wally proposal file, the
public dashboard card, and the scheduled workflow.

Needs Johnny's decision before it does anything automatically:

1. Whether to fold `watchlists/macro_candidates_proposed.yaml` entries into
   a real watchlist (which one, what buy price).
2. Whether new tickers should be added to `tickers.yaml` so Bob/Shorty start
   monitoring their announcements.
3. Whether research-house monitoring (Bridgewater/PIMCO/BlackRock/etc.,
   section 5) should scrape public pages automatically, or stay a manual
   "paste what you read" input for now — no credentials or paywall bypass
   exist for any of them, so v1 ships with the registry and scoring wired
   up but no live scraper; this is the one section of the brief not fully
   automated, and is called out explicitly rather than silently skipped.
4. Whether Micky's Macro should write into Harry's `data/harry_flags.yaml`
   equivalent or similar cross-agent files later (explicitly out of scope
   for this pass, matching the "later pass" precedent on Bob's own
   acquisition/fundraise memos).
