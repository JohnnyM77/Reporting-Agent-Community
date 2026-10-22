# Regional agents — Bob USA and Singapore Slinger

These are separate filing-monitoring pipelines for markets whose data sources and access requirements differ from the ASX workflow.

## Bob USA — US SEC filings

**Purpose:** Monitor configured US portfolio tickers for new SEC 10-K and 10-Q filings, analyse relevant filings and publish a digest/dashboard update.

**Confirmed in workflow**
- Runs daily and can be manually triggered for a single ticker or the full configured US portfolio.
- Tracks filing accession identifiers in `state_seen_us.json` so the same filing is not repeatedly analysed.
- Supports a dry run.
- Runs on GitHub-hosted Ubuntu; SEC EDGAR does not require the special browser/TLS handling used by the SGX workflow.

Key files: [workflow](../.github/workflows/us_daily.yml), [`us_agent.py`](../us_agent.py), and the US ticker configuration in [`tickers.yaml`](../tickers.yaml).

## Singapore Slinger — SGX announcements

**Purpose:** Fetch, classify and analyse SGX announcements, with deep analysis for results and a daily email/dashboard update.

**Confirmed in workflow**
- Runs daily at **08:15 Singapore time** and can be manually triggered.
- Supports ticker overrides, lookback hours, dry run, fetch-only mode, and a longer lookback for a named ticker’s last half/full-year results.
- Uses the self-hosted Windows runner because the SGX announcements endpoint imposes browser/TLS-fingerprint constraints that the GitHub-hosted Ubuntu runner cannot reliably satisfy.
- Maintains its own seen-state and publishes dashboard data.

Key files: [workflow](../.github/workflows/sgx_daily.yml), [`sgx_agent.py`](../sgx_agent.py), [`sgx_fetch.py`](../sgx_fetch.py), [`sgx_classify.py`](../sgx_classify.py), and [`sgx_email.py`](../sgx_email.py).

## Why separate pipelines?

The high-level job resembles Bob’s — find new filings, classify them, analyse what matters, send a digest — but exchange APIs, filing types and access controls differ. Keeping market-specific retrieval separate avoids pretending one fetcher can reliably handle every exchange.
