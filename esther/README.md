# Esther the Wrestler

> She doesn't write the story. She finds out whether the story survives the numbers.

The editorial and valuation layer on top of Bob, Wally, Sally, Harry and Theo.
For one company at a time she works out what actually changed, challenges JM's
thesis in private, proposes the Simply Wall St slider inputs for JM's Narrative
case, and drafts a 300-500 word public Narrative in JM's voice. She emails it the same way the other
agents do.

## Run it

GitHub: **Actions → Esther the Wrestler → Run workflow**, then pick tickers and a mode.

Locally:

```bash
python -m esther run --tickers CPU,BXB,BHP,NHC                  # FULL NARRATIVE
python -m esther run --tickers NHC --mode challenge             # CHALLENGE MY THESIS
python -m esther run --tickers CPU --mode thesis                # THESIS CHECK
python -m esther run --tickers BHP --mode valuation --price BHP=59.80   # CHANGE VALUATION
python -m esther run --tickers NHC --mode quick --source NHC=https://www.asx.com.au/...pdf
python -m esther run --tickers CPU --analysis-dir saved/ --no-email     # re-render a saved analysis
```

| Spec button | How to do it |
|---|---|
| Full narrative / Quick update | `--mode full` / `--mode quick` |
| Valuation only / Change valuation | `--mode valuation`, with `--price` or `--notes "use 12% margin"` |
| Thesis check | `--mode thesis` → THESIS INTACT or THESIS CHANGED, with the reason |
| Challenge my thesis | `--mode challenge` |
| Regenerate | run it again (the previous run is used for "what changed") |
| Edit narrative / Publish-ready copy | the email's "Publish-ready copy" block, or the attached `TICKER.md` |

## How it works

1. **Context** (`context.py`): JM's thesis (`theses/`), value-chart settings
   (`valuations/`), and the ticker's rows from Harry, Theo, Sally, Wally and Bob
   (`docs/data/*.json`). Portfolio status (owned / watching / sold) comes from
   `data/decisions.json` and the thesis file, never from the model, so the
   `Disc: I own shares.` line can't be invented.
2. **Research and analysis** (`analyst.py`, `prompts.py`): one model call with
   web search on, plus any ASX PDFs you pass. Strict JSON back. If it fails a
   hard quality check (over 550 words, banned phrases, no evidence, no
   statutory vs underlying) it gets one repair call.
3. **Valuation** (`valuation.py`): SWS takes one set of sliders, so the model
   proposes ONE Narrative case (growth, margin, P/E) anchored on guidance, the
   company's better-year margins and the stock's own multiple: the case JM
   believes as an owner. Code computes the value the way SWS does (revenue × (1+g)^5 × margin × P/E
   ÷ shares, discounted at the SWS discount rate, converted US$→A$ where
   needed). It also shows the reverse-DCF ("what growth is Mr Market pricing
   in?") and, on a separate line, what SWS leaves out: today's dividend
   collected for five years. A private stress case (what it's worth if the key
   assumption fails) is shown to JM only, never published and never averaged in.
4. **Quality control** (`quality.py`): em dashes are scrubbed; banned phrases,
   word count, title and evidence are checked, and the public narrative is
   rejected if it talks about trimming, selling or position size. The model's own
   self-check is shown separately and labelled as such.
5. **Output** (`render.py`): a table-only HTML email with the SWS inputs block
   at the top, plus one markdown file per company attached.

Outcomes are `OK`, `FAILED_API`, `FAILED_INVALID` or `SKIPPED_CAP`, and a
failed company is rendered as failed. A broken run never looks like a clean one.

## Settings

| Env | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | | required |
| `ESTHER_MODEL` | `claude-opus-4-6` | repo variable in the workflow |
| `ESTHER_MAX_TOKENS` | `16000` | |
| `ESTHER_MAX_TICKERS` | `8` | companies per run |
| `ESTHER_STORE_DIR` | `esther_data/` (gitignored) | previous runs; the workflow uses the private repo |
| `EMAIL_FROM` / `EMAIL_TO` / `EMAIL_APP_PASSWORD` | | same secrets as every agent |

## What Esther can't see (yet)

- **Your inbox.** In Actions she reads the other agents' published JSON, not
  their emails. Bob's history keeps only headlines, so for results she relies
  on web search or the PDFs you pass with `--source`.
- **Simply Wall St itself.** Tell her about your live narrative with
  `--notes` (e.g. "live NHC narrative uses 12.74% growth, FV $6").
