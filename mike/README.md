# Mike | Stock Quality

> How good has this business demonstrably been? Not what it might become.

Mike scores Mikebrisy's **Stock Quality Assessment Framework v3.1** ("True 0-5
Demonstrated Track Record Rubric", Strawman, October 2026) exactly as written,
then emails a scorecard in Bob's card style with the full assessment as a PDF.

## Run it

GitHub: **Actions → Mike Stock Quality → Run workflow**, pick `mikebrisy_sample`
or `portfolio` (open holdings in `data/decisions.json`, ETFs excluded), or type
tickers.

```bash
python -m mike --list mikebrisy_sample --email
python -m mike --list portfolio --email
python -m mike --tickers PME,TNE --no-evidence      # quantitative only: Market Position unscored, DRAFT
python -m mike --tickers PME --cache-dir qcache     # reuse saved /fundamentals JSON
```

Outputs in `outputs/mike/<list>/`: `mike_report.pdf`, `mike.json`, `email.html`.

## How it follows the framework

| Framework section | Where |
|---|---|
| 4.1-4.6 base-score tables | `mike/rubric.py`, one function per criterion, tables copied verbatim |
| 4.3 five evidence tests | `mike/evidence.py`: one Claude call (web search) proposes; code awards a point only with specific historical evidence and a source |
| Permitted overlays, max +/-0.5 | data overlays in `rubric.py`, model overlays validated in `evidence.py`, manual ones in `config/mike.yaml`; capped in `assess.py` |
| No forward-looking uplift | forward wording (guidance, pipeline, TAM, backlog, targets) can never raise a score |
| Anti-double-counting | the same evidence cannot lift two criteria |
| 6 Quality Trend | `mike/trend.py`, last three FYs against the three before; never changes the score |
| 7 classification, risk flags | `assess.py`: Very Low / Low / Medium / Medium-High / High; any criterion <=1 flagged, 0 extreme |
| 8 QA/QC | `mike/qaqc.py`: independent recalculation from raw JSON, exact mean, band tests, every 8.5 check, 8.7 certification; PASS or DRAFT |
| 8.7 visual/document | the PDF is rendered, reopened and checked per company before certification |
| 10 standard output | every company opens with the section 10 scorecard |

## What Mike cannot do from EODHD (and says so)

- **Underlying earnings.** EODHD is statutory only. The framework says statutory
  first; one-offs stay in the numbers, and the model lists items the company
  called one-off for you to review. They are never applied automatically.
- **Capitalised development, maintenance vs growth capex, covenants, maturities.**
  Not on EODHD; recorded as inapplicable in every workpaper.
- **Organic vs acquired growth.** Inferred from goodwill/intangibles growth.
- **Banks and insurers.** The framework allows sector metrics; Mike has none
  yet, so these stay DRAFT with the reason.
- **WACC.** A stated assumption (9% default, `config/mike.yaml`).

Settings: `MIKE_MODEL` (default `claude-sonnet-4-6`), `MIKE_MAX_TOKENS` (12000),
`MIKE_MAX_LLM_CALLS` (40 per run), `MIKE_WORKERS` (4 parallel calls).
