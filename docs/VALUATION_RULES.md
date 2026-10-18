# Valuation rules: what "cheap" means

Every buy multiple Wally and Sally use comes from one place:
`config/valuation_archetypes.yaml`, applied by `shared/classifier.py`. Nothing
else may hard-code a multiple.

## 1. Archetypes

Each company gets one archetype. The archetype sets a base buy P/E and which
EPS the multiple is applied to.

| Archetype | Base P/E | EPS basis | Typical business |
|---|---|---|---|
| compounder | 25x | TTM | Wide moat, ROIC above 20%, long reinvestment runway |
| quality_steady | 18x | TTM | Has a moat; mid-single to low-double-digit growth |
| defensive_mature | 15x | 3-year average | Low growth, regulated, staples, healthcare services |
| cyclical | 10x | 7-year average (mid-cycle) | Miners, energy, commodity-linked |
| financial | 12x | TTM (P/B shown as a cross-check) | Banks, insurers, MQG |
| property_infra | none | none | REITs, toll roads, utilities: dividend yield / P/AFFO |
| early_growth | none | none | Pre-profit or erratic earnings: P/S or P/FCF |

`unclassified` means EODHD had no data (an ETF, or an exchange not on the plan).
It gets no multiple and confidence 0, so it always shows at the top of the review.

## 2. Modifiers (P/E archetypes only, each +/- 2x)

- ROIC above 20%: +2x. ROIC below 8%: -2x.
- Net cash: +2x. Net debt above 2.5x EBITDA: -2x.
- No loss year in 10 years and low EPS volatility: +2x. Any loss year in 10: -2x.
- `structural_headwind: true` (set by you, e.g. regulation or fee cuts): -2x.

For financials the ROIC and net-debt modifiers are skipped: a bank's debt is its
deposits, so they mean nothing.

ROIC is NOPAT (EBIT x (1 - tax rate)) over equity plus debt less cash, the
median of the last three years. All inputs are EODHD statements.

## 3. Guardrails

1. The final multiple never exceeds the stock's own 10-year median P/E (EODHD
   month-end prices over statutory EPS in force on each date).
2. Floor 6x, ceiling 35x.
3. A ticker override (multiple plus a one-line reason) always wins, and skips
   every guardrail.

## 4. How a ticker gets its archetype

The classifier suggests, you decide. Sector rules come first
(Materials/Energy -> cyclical; Banks/Insurance/Diversified Financials ->
financial; Real Estate/Utilities/Transport infrastructure -> property_infra;
negative or missing EPS -> early_growth). Anything left is split on ROIC and
revenue growth into compounder, quality_steady or defensive_mature.

Confidence (0-1) drops when data is missing, history is short, an awkward
industry sits inside a sector rule, or a metric is within 15% of a threshold.

## 5. Confirm / override

`config/ticker_archetypes.yaml` has one entry per ticker:

```yaml
PWH.AX:
  archetype: defensive_mature
  status: auto            # auto | confirmed
  override_multiple: null # e.g. 22
  override_reason: ""     # required in spirit when override_multiple is set
  structural_headwind: false
  lists: [JM Watch List]
  active: true
  last_classified: '2026-10-06'
```

- To confirm: set `status: confirmed` (and change `archetype` if you disagree).
- To override the multiple: set `override_multiple` and `override_reason`.
- A `confirmed` entry is never changed by the sync or the classifier, except
  `lists` and `active`. Only change it on the owner's instruction.

## 6. Staying current

`sync_archetypes()` runs at the start of every Wally and Sally run, and the
**Archetype sync** workflow runs on any push to `watchlists/**`:

- a ticker with no entry is classified and written as `status: auto`;
- a ticker on no watchlist gets `active: false` (history is kept);
- unconfirmed entries are re-classified after 90 days, and `unclassified` ones
  every run;
- Wally's email lists new `auto` tickers under "New tickers needing
  confirmation" once, with the suggested archetype and multiple.

Portfolio holdings in `tickers.yaml` are included (list "Portfolio") so Sally
has a multiple for everything she reviews.
