# Harry Hindsight

**Job:** challenge the investment decision before hindsight makes the answer obvious.

Harry is the chief sceptic above the other agents. He does not primarily fetch announcements or screen prices. He reads Bob, Sally, Wally and Theo's existing outputs, checks deterministic triggers, and calls the model only when something could materially change the investment conclusion.

## The questions Harry asks

1. What would have to be true for my current conclusion to be wrong, and is there evidence it is already happening?
2. Would I make the same decision today if I did not already own the shares?
3. Am I evaluating the business, or defending a decision I have already made?

If nothing material has changed, Harry should say so. He is a sceptic, not a permanent bear.

## What can trigger a review

- A Sally trim-candidate flag on a holding, or a high valuation percentile combined with proximity to the 52-week high.
- A Bob HIGH IMPACT event, with configured severity upgrades for certain risks.
- A meaningful move in a JM Watch List name, a new Bob event, a Wally target crossing, a newly strained Theo thesis pillar, a new thesis version or a valuation-config change.
- Wally's top opportunity candidates above the configured score threshold.
- Scheduled portfolio reviews and autopsies of previous warnings.

The gates are deterministic. **No gate, no model call.** That keeps cost down and prevents the model from inventing a reason to comment on every quiet day.

## What a full report includes

- The strongest opposing case.
- A thesis test and checks for changes in the thesis history.
- Hamilton Helmer's 7 Powers, including tests of both the claimed power and its durability.
- A Charlie Munger tendency scan and a code-enforced Lollapalooza gate.
- A verdict with an explicit severity reason.
- Falsifiable predictions so a later review can check whether the warning was right.
- Evidence references and labels distinguishing facts from interpretation or management claims.

Harry's code validates outputs. For example, an unsupported factual claim is downgraded to interpretation; a bias assertion needs an evidence reference; and a warning without a falsifiable prediction is rejected. The Munger scan is a checklist, not a psychological diagnosis.

## Outputs and private data

Harry sends an email and PDF reports, publishes a dashboard payload at `docs/data/harry.json`, and writes structured events for future aggregation. Case files, SQLite records, the bias profile and decision data belong in the private store, not the public repository.

The documented production store defaults to a private repository. If that private store is not configured, the scheduled workflow can fail deliberately rather than silently falling back and losing history.

## Run examples

```bash
python -m hindsight sell NHC
python -m hindsight sell NHC --dry-run
python -m hindsight run
python -m hindsight run --mode portfolio
python -m hindsight run --mode autopsy
python -m hindsight respond NHC --action held --note "Waiting for FY results"
```

The available response actions include `held`, `sold`, `trimmed`, `added` and `ignored`. Those responses feed future reports and autopsies.

## Key files

- [`hindsight/README.md`](../../hindsight/README.md)
- [`hindsight/adapters.py`](../../hindsight/adapters.py): reads other agents' outputs.
- [`hindsight/gating.py`](../../hindsight/gating.py): deterministic triggers.
- [`hindsight/validators.py`](../../hindsight/validators.py): evidence and output checks.
- [`config/hindsight.yaml`](../../config/hindsight.yaml): thresholds and settings.
- [`docs/CAPTAIN_HINDSIGHT_ARCHITECTURE.md`](../CAPTAIN_HINDSIGHT_ARCHITECTURE.md): detailed architecture and assumptions.

## In one sentence

Harry is the **challenge function**: he looks for evidence that the thesis, valuation or behaviour has changed, and asks the awkward question before a loss gets any bigger.
