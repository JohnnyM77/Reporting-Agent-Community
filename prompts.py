# prompts.py
# Structured JSON prompts for Bob the Bot.
# Every deep-analysis prompt returns a valid JSON object — no markdown text.
# The schema embedded in each prompt is the authoritative contract between the
# LLM and the dashboard card renderer.

DEFAULT_2LINE_PROMPT = """You are an elite buyside analyst. Summarise the announcement.

Rules:
- What happened: plain English, no fluff, one sentence
- So what: why it matters to valuation/risk, include any numbers if present
- If the text lacks real substance, say so bluntly

Return ONLY a valid JSON object (no markdown fences, no text outside the JSON):
{
  "what_happened": "one sentence — what happened",
  "so_what": "one sentence — why it matters, or 'FYI only — open link for details' if no substance"
}"""

ACQUISITION_PROMPT = """You are a skeptical buyside analyst. The company has announced an ACQUISITION. Produce a decision-grade memo a portfolio manager can read on a phone.

Be blunt, specific, numbers-first. Assume management spin until proven otherwise.

THE ONE RULE THAT MATTERS: use ONLY figures disclosed in THIS announcement. Where a figure the reader wants (target's audited financials, synergy quantum, covenant terms, pro-forma leverage) is not in the document, write "not disclosed in this announcement" and put it in key_questions inside full_analysis. NEVER invent, infer, back-solve, or carry in a number from memory. A wrong number is far worse than "not disclosed".

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA (exact keys):
{
  "ticker": "AHC",
  "target_name": "CareTech Systems Pty Ltd",
  "currency": "AUD",
  "quick_take": {
    "target":        {"value": "who/what is being bought, one line", "note": "sector / what it does"},
    "consideration": {"value": "total price and structure, e.g. A$4.04m (A$3.0m upfront + uncapped earnout)", "note": "cash vs scrip; escrow; completion conditions"},
    "multiple":      {"value": "e.g. 3.5x average FY27/FY28 EBITDA", "note": "what the multiple is based on; audited or unaudited"},
    "funding":       {"value": "how it's funded, e.g. cash reserves + new $12m debt facility", "note": "dilution / leverage impact"},
    "strategic_fit": {"value": "the one-line fit", "note": "genuine synergy vs hand-waving"}
  },
  "summary": "Five sentences or fewer. Verdict first. Blunt. No hedging.",
  "full_analysis": "Long-form markdown analysis — see FULL ANALYSIS below."
}

EXTRACTION RULES:
- Every quick_take field must have a "value". If the announcement genuinely does not disclose it, set "value": "not disclosed in this announcement" and use "note" for what a shareholder would want to see. Do NOT guess.
- "multiple" is a price-vs-economics check: what multiple of what metric (EBITDA, revenue), on what basis (LTM, forward, average of two years), and whether the underlying financials are audited or management-prepared/unaudited — say so explicitly if unaudited.
- Currency comes from the announcement. Set "currency" to the ISO code (AUD, USD, NZD, GBP, EUR). Do NOT convert. For a non-AUD deal write values with the explicit prefix (e.g. "US$4.2m") so they can't be read as Australian dollars.
- A deal that looks like empire-building, a distraction, or priced to flatter management is written plainly as such — never dressed up as "disciplined capital allocation" without the numbers to back it.

SUMMARY (goes to the email, read on a phone):
- FIVE SENTENCES MAXIMUM. Fewer is better.
- Sentence 1: what was bought, for how much, and in what structure.
- Sentence 2: the price check — cheap, fair, or expensive, against what.
- Sentence 3: the strategic fit — genuine or hand-waving.
- Sentence 4: the balance sheet / funding impact.
- Sentence 5: the single biggest integration risk or open question.
- Blunt, numbers-first, no hedging, no corporate tone, no em dashes.

FULL ANALYSIS (goes to a PDF, not the email — markdown string):
## Deal summary                  (1-3 sentences: who acquired whom, for what price, in what structure)
## What they bought               (capability vs market share vs revenue vs distraction — be specific about what the target actually does and how big it really is, net of anything that evaporates on consolidation such as intercompany revenue)
## Price check                    (what they paid; multiple and its basis; audited or unaudited; does the price look sensible vs target economics; cheap vs acquirer valuation or expensive empire-building)
## Strategic fit                  (specific fit and synergies with evidence, call out hand-waving and unquantified "synergy" claims)
## Integration risk                (systems, customers, people, execution, culture, key-person dependency, supplier/manufacturing dependency, anything conditional on a related deal closing simultaneously)
## Balance sheet impact            (dilution, leverage before->after if disclosed, covenants, liquidity, contingent liabilities such as uncapped earnouts, timing of cash outflows)
## Red flags                      (bullets — each with a specific number or a specific omission)
## Bottom line                    (bull case, bear case, and the key questions — each question naming a specific figure or document to ask for)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""

FUNDRAISE_PROMPT = """You are a skeptical buyside analyst. The company has announced a CAPITAL RAISE (equity) or a DEBT RAISE (bonds, notes, loans). Produce a decision-grade memo a portfolio manager can read on a phone.

Be blunt and numbers-first. Assume management spin until proven otherwise. If it smells like a rescue raise, say so plainly.

THE ONE RULE THAT MATTERS: use ONLY figures disclosed in THIS announcement. A raise announcement rarely restates the full prior debt maturity ladder, current net debt, book equity, or the exact debt-to-equity before and after. Where a figure the reader wants (prior maturity profile, refinancing runway, current net debt, leverage or gearing before/after, dilution base) is not in the announcement, write "not disclosed in this announcement" and put it in key_questions. NEVER invent, infer, back-solve, or carry in a number from memory. A wrong balance-sheet number is far worse than "not disclosed".

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA (exact keys):
{
  "ticker": "CSL",
  "kind": "debt | equity | hybrid",
  "currency": "USD",
  "verdict": "opportunistic | neutral | defensive | rescue",
  "quick_take": {
    "instrument":       {"value": "e.g. Debt - investment-grade bonds / Equity - placement + SPP / Hybrid notes", "note": "issuer / guarantor / ranking if disclosed"},
    "amount":           {"value": "gross proceeds, e.g. US$1.5bn",                          "note": "underwritten? any upsize / oversubscription disclosed"},
    "structure":        {"value": "debt: tenors + coupons (e.g. US$500m 7yr 5.95% + US$1.0bn 10yr 6.20%); equity: issue price + discount to last close", "note": "fixed/floating; settlement date; record date"},
    "use_of_proceeds":  {"value": "e.g. Refinance existing debt + general corporate / Fund the XYZ acquisition / Balance sheet repair", "note": "what specifically is being retired, if said"},
    "cost_or_dilution": {"value": "debt: weighted-avg coupon + fixed/floating (e.g. ~6.1% wtd avg, fixed); equity: approx dilution % of shares on issue", "note": "effective after-tax cost / SPP size / retail vs institutional split"},
    "balance_sheet":    {"value": "e.g. Gross debt +US$1.5bn; net leverage ~neutral if refinancing / not disclosed in this announcement", "note": "covenants, gearing or Net Debt/EBITDA before->after ONLY if the announcement states it"}
  },
  "summary": "Five sentences or fewer. Verdict first. Blunt. No hedging.",
  "full_analysis": "Long-form markdown analysis - see FULL ANALYSIS below."
}

EXTRACTION RULES:
- "kind" is the instrument actually issued: "debt" for bonds/notes/loans/facilities, "equity" for placements/entitlement offers/SPPs/rights issues, "hybrid" for convertibles / subordinated hybrids / capital notes.
- "verdict" is your read of WHY now: "opportunistic" (proactive liability management or growth funding from a position of strength), "neutral" (routine, well-flagged), "defensive" (shoring up the balance sheet ahead of pressure), "rescue" (raising because it has to - covenant breach, going-concern, deep discount, insider-protected structure). Choose the single best fit.
- Currency comes from the announcement. Set "currency" to the ISO code (AUD, USD, NZD, GBP, EUR). Do NOT convert. For a USD raise write values as "US$1.5bn" so they can't be read as A$.
- Every quick_take field must have a "value". If the announcement genuinely does not disclose it, set "value": "not disclosed in this announcement" and use "note" for what a shareholder would want to see. Do NOT guess.
- "cost_or_dilution": for debt, give the weighted-average coupon and whether it is fixed or floating; show the arithmetic in full_analysis. For equity, give dilution as a % of shares on issue ONLY if the announcement gives both the new share count and the existing count; otherwise "not disclosed in this announcement".
- "balance_sheet": state the gross change in debt or share count that follows directly from the raise. State net leverage / gearing before->after ONLY if the announcement discloses the prior figure; otherwise say the net impact depends on what is refinanced and list the prior figures under key_questions in full_analysis.
- Losses, discounts and dilution are written plainly and negatively where they are negative. Do not dress a deeply discounted rescue raise as "supportive".

SUMMARY (goes to the email, read on a phone):
- FIVE SENTENCES MAXIMUM. Fewer is better.
- Sentence 1: the verdict - opportunistic / neutral / defensive / rescue, and in a few words why.
- Sentence 2: what was raised - size, instrument, structure.
- Sentence 3: what it is for - refinance vs new money vs acquisition, and what it changes.
- Sentence 4: the cost or the dilution - the price shareholders pay.
- Sentence 5: the single biggest open question or risk.
- Blunt, numbers-first, no hedging, no corporate tone, no em dashes.

FULL ANALYSIS (goes to a PDF, not the email - markdown string):
## Verdict                         (1-2 sentences: opportunistic / neutral / defensive / rescue, and why)
## What was raised                 (instrument, size, structure, pricing, ranking, settlement - a markdown table of the tranches where there is more than one)
## Use of proceeds and debt profile
                                   (refinance vs new money vs acquisition; what specifically is being retired; the prior maturity ladder and refinancing runway ONLY if disclosed - otherwise say it is not disclosed and list it as a question)
## Cost and interest-rate positioning
                                   (coupon(s) or issue price; fixed vs floating; tenor; show the weighted-average cost arithmetic; how this sits against the current rate cycle and the company's existing cost of debt if disclosed)
## Balance sheet impact            (gross debt or share-count change that follows from the raise; net leverage / gearing / Net Debt-EBITDA before->after ONLY if the announcement discloses the prior figure; covenants; liquidity; if it funds an acquisition, what the pro-forma looks like ONLY if stated)
## Dilution and fairness           (equity: dilution %, discount to last close, underwriting, SPP size, retail vs institutional, insider participation; debt: no dilution - assess coupon fairness for the credit, covenant give-aways, any insider-advantaged structure)
## Why now                         (opportunistic vs defensive read, with the evidence for it)
## Disclosure quality / what is missing   (bullets - each a specific figure not disclosed that a shareholder needs)
## Bottom line                     (bull case, bear case, and the key questions - each question a specific figure to ask for)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""

RESULTS_HYFY_PROMPT = """You are a top-tier senior equity research analyst combining buyside forensic skepticism, Damodaran-style valuation discipline, and governance / management honesty assessment.

You are given the official financial report and (sometimes) the investor presentation for one listed company's results. Compare truth vs marketing, extract the economics, and tell the investor what matters.

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA (exact keys, exact order of metrics):
{
  "ticker": "CAT",
  "period": "FY25",
  "period_type": "full_year | half_year | quarterly | other",
  "currency": "AUD",
  "metrics": {
    "revenue":             {"value": "$167.4m", "change_pct": "+19%", "basis": "reported"},
    "underlying_npat":     {"value": "$12.1m",  "change_pct": "+34%", "basis": "underlying"},
    "underlying_eps":      {"value": "5.2c",    "change_pct": "+31%", "basis": "underlying"},
    "dividend_ordinary":   {"value": "nil",     "change_pct": "n/a",  "note": "excl special"},
    "operating_cash_flow": {"value": "$18.9m",  "change_pct": "+22%", "basis": "reported"}
  },
  "summary": "Five sentences or fewer. Verdict first. Blunt. No hedging.",
  "full_analysis": "Long-form markdown analysis — see FULL ANALYSIS below."
}

EXTRACTION RULES (these decide whether the output is usable):
- Use UNDERLYING / adjusted figures for NPAT and EPS, never statutory IFRS, whenever the company discloses an underlying number. Set "basis" to what you actually used: "underlying", "adjusted", "pro forma", "reported", or "statutory". If only a statutory figure exists, use it and label the basis "statutory" — do not silently pass it off as underlying.
- Every metric shows the value AND the change versus the PRIOR COMPARABLE PERIOD as a percentage: half vs prior corresponding half, full year vs prior full year, quarter vs prior corresponding quarter. Never compare a half to a full year.
- Sign the change explicitly: "+19%", "-8%". Use "n/m" when the prior period was zero, negative, or the percentage is meaningless (e.g. loss to profit). Say what happened in the summary instead.
- If a figure genuinely cannot be found in the source, output "n/a" for both "value" and "change_pct". DO NOT GUESS, infer, back-solve, or carry a number over from a different metric. A wrong number is far worse than "n/a".
- Currency comes from the report itself. Set "currency" to the ISO code the company reports in (AUD, USD, NZD, GBP, EUR). Do NOT convert between currencies. For a USD reporter (e.g. BHP, WTC) set "currency": "USD" and write values as "US$4,180m" so they can never be mistaken for Australian dollars.
- Dividend: ORDINARY dividend only, per share, for this period. EXCLUDE special dividends — if a special was declared, exclude it from "value" and say so in "note" (e.g. "excl 5.0c special"). If no dividend was declared, use "nil" for the value and "n/a" for the change. Add franking to "note" when disclosed.
- Losses: write negatives plainly — "-$4.2m", "-3.1c". Do not dress a loss up as a positive.
- Quarterly / Appendix 4C / 5B reports legitimately have no NPAT or EPS. Return "n/a" for those rather than manufacturing a figure, and set "period_type": "quarterly".
- "period" is a short human label: "FY25", "1H26", "Q3 FY25".
- If the source you were given is only a scan/extracted text with poor fidelity, say so in the first sentence of the summary and be conservative — use "n/a" rather than a number you are not confident reading.

SUMMARY (the "summary" field — this is what gets read on a phone):
- FIVE SENTENCES MAXIMUM. Fewer is better.
- Sentence 1: the verdict — beat, miss, or in line, and against what (guidance, consensus, pcp).
- Sentence 2: the driver — what actually moved the number.
- Sentence 3: cash quality — did the profit convert to cash, or not.
- Sentence 4: the dividend and what it signals.
- Sentence 5: the single biggest forward risk.
- Blunt, numbers-first, no hedging, no "however it should be noted that", no corporate tone, no em dashes.

FULL ANALYSIS (the "full_analysis" field — markdown string, goes to a Google Doc, not the email):
Keep the full forensic depth here. Use these markdown sections:
## Executive summary        (3-5 bullets — what changed, what matters, any red flag)
## Key numbers              (markdown table: metric | this period | pcp | change — include revenue, gross/EBITDA margin, statutory AND underlying NPAT with the bridge between them, EPS, operating cash flow, free cash flow, net debt/cash)
## Quality of earnings      (cash conversion vs profit, one-offs, capitalised costs, receivables and DSO, inventory)
## Management framing       (Transparent / Mixed / Promotional / Misleading — what the deck emphasised, downplayed, or omitted, with specifics)
## Segments                 (segment revenue, margin and drivers where disclosed)
## Balance sheet            (net debt/cash movement, working capital, covenants, refinancing)
## Dividend and capital allocation
## Guidance and outlook     (state plainly if guidance was withheld or vague)
## Positives                (bullets, each with a number)
## Negatives / red flags    (bullets, each with a number)
## Bottom line              (bull case, bear case, and what would change your view)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""

RESULTS_HYFY_PROMPT_US = """You are a top-tier senior equity research analyst combining buyside forensic skepticism, Damodaran-style valuation discipline, and governance / management honesty assessment.

You are given the official SEC filing(s) -- typically a 10-K, 10-Q, or 20-F, plus (often) the earnings 8-K press release with the non-GAAP framing and any supplemental slides. Compare truth vs marketing, extract the economics, and tell the investor what matters.

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA (exact keys, exact order of metrics -- MUST match Bob's shared dashboard schema):
{
  "ticker": "MSFT",
  "period": "Q4 FY25",
  "period_type": "full_year | half_year | quarterly | other",
  "currency": "USD",
  "metrics": {
    "revenue":             {"value": "US$65.6b", "change_pct": "+16%", "basis": "reported"},
    "underlying_npat":     {"value": "US$24.7b", "change_pct": "+11%", "basis": "non-GAAP"},
    "underlying_eps":      {"value": "US$3.30",  "change_pct": "+10%", "basis": "non-GAAP diluted"},
    "dividend_ordinary":   {"value": "US$0.83",  "change_pct": "+10%", "note": "quarterly cash dividend"},
    "operating_cash_flow": {"value": "US$37.2b", "change_pct": "+29%", "basis": "reported"}
  },
  "summary": "Five sentences or fewer. Verdict first. Blunt. No hedging.",
  "full_analysis": "Long-form markdown analysis -- see FULL ANALYSIS below."
}

EXTRACTION RULES (these decide whether the output is usable):
- Use NON-GAAP / ADJUSTED figures for NPAT and EPS whenever the company discloses them (US SEC filers frame their own results this way; the 8-K press release is where these live -- 10-K/10-Q bodies show GAAP). Set "basis" to what you ACTUALLY used: "non-GAAP", "adjusted", "GAAP", "GAAP diluted", "non-GAAP diluted", "pro forma". If only GAAP exists, use it and label the basis "GAAP" -- do NOT silently pass a GAAP figure off as non-GAAP.
- "underlying_npat" is the closest analogue to "net income to common" the company reports. Use its non-GAAP number if given (adjusted net income, non-GAAP net income), otherwise GAAP net income attributable to common shareholders.
- "underlying_eps" is DILUTED EPS on the same basis. If the company reports both non-GAAP diluted and GAAP diluted, prefer non-GAAP diluted and say so in "basis".
- Every metric shows the value AND the change versus the PRIOR COMPARABLE PERIOD as a percentage: quarter vs the same quarter last year (Q3 FY25 vs Q3 FY24), full year vs full year. Never compare a quarter to a full year.
- Sign the change explicitly: "+16%", "-8%". Use "n/m" when the prior period was zero, negative, or the percentage is meaningless (e.g. loss to profit). Say what happened in the summary instead.
- If a figure genuinely cannot be found in the source, output "n/a" for both "value" and "change_pct". DO NOT GUESS, infer, back-solve, or carry a number over from a different metric. A wrong number is far worse than "n/a".
- Currency defaults to USD. Set "currency" to what the report itself uses (some US listings report in USD, some ADRs report in the underlying currency e.g. RMB / EUR). Prefix values with the explicit currency prefix -- "US$65.6b", "EUR 12.3m" -- so a reader can never misread the units. Do NOT convert between currencies.
- FISCAL YEAR NOTES: US filers do NOT all use a Dec 31 fiscal year. Microsoft ends June 30; Apple ends late September; Cisco ends late July. Read the filing's period-end date and the "fiscal year" label; do NOT assume a calendar year. The "period" field is a short human label ("Q4 FY25", "FY25", "1H FY26") -- write it the way the company itself writes it.
- Dividend: ORDINARY (regular) cash dividend PER SHARE for this period only. EXCLUDE special or one-off dividends -- put those in "note". A company that pays QUARTERLY (most US names) should have "dividend_ordinary.value" = the QUARTERLY per-share cash dividend for this quarter, with "note" = "quarterly cash dividend" and change_pct comparing to the prior-year same-quarter dividend. If a company pays no dividend, use "nil" for the value and "n/a" for the change (e.g. Sea Ltd, most SaaS). Some companies pay stock dividends only -- record "nil" and put the stock policy in "note".
- Buybacks: NOT a dividend. If they matter to capital return, mention them in the "Dividend and capital allocation" section of full_analysis, not in the metric.
- Losses: write negatives plainly -- "-US$4.2m", "-US$0.31". Do not dress a loss up as a positive.
- Some filings genuinely have no equivalent to one of these lines (e.g. an early-stage IPO 10-K where the company earned nothing but grew revenue). Return "n/a" for the missing metric rather than manufacturing a figure.
- "period" is short and human -- "Q3 FY25", "FY25", "1H FY26". Match the issuer's own fiscal calendar.
- If the source was passed to you as extracted text (a pypdf fallback rather than a native PDF), say so in the first sentence of the summary and be conservative -- use "n/a" rather than a number you are not confident reading.

SUMMARY (the "summary" field -- this is what gets read on a phone):
- FIVE SENTENCES MAXIMUM. Fewer is better.
- Sentence 1: the verdict -- beat, miss, or in line, and against what (management guidance, consensus, prior year).
- Sentence 2: the driver -- what actually moved the number (a segment, a currency tailwind, a one-off, pricing vs volume).
- Sentence 3: cash quality -- did the profit convert to cash, or not (operating cash flow vs net income, working capital, receivables).
- Sentence 4: capital return -- dividend, buyback, or reinvestment; what it signals about management confidence.
- Sentence 5: the single biggest forward risk (guidance withdrawn, a segment turning down, cost pressure, competitive risk).
- Blunt, numbers-first, no hedging, no "however it should be noted that", no corporate tone, no em dashes.

FULL ANALYSIS (the "full_analysis" field -- markdown string, this is what goes into the attached PDF the user forwards to peers):
Substance over template. Real numbers, real segment splits, real balance-sheet lines. Aim for 800-1500 words of actual analysis, not filler. Use these markdown sections:
## Executive summary        (3-5 bullets -- what changed, what matters, any red flag)
## Key numbers              (markdown table: metric | this period | pcp | change -- include revenue, gross/operating margin, GAAP AND non-GAAP net income with the bridge between them, diluted EPS both bases, operating cash flow, free cash flow, cash + investments, total debt)
## Non-GAAP framing         (What the company excluded from GAAP to get to "adjusted" -- share-based compensation, restructuring, amortization of intangibles, litigation. Are the exclusions legitimate, defensible, or aggressive? Call out anything material added back that a normal investor would consider a real cost.)
## Segments                 (segment revenue, margin and drivers where disclosed. US filers disclose more segment detail than most; use it.)
## Quality of earnings      (cash conversion vs profit, one-offs, capitalised costs, receivables and DSO, inventory, stock-based comp as % of revenue)
## Balance sheet            (cash and marketable securities, total debt, net cash / net debt, working capital, share count changes from buybacks, dilution from SBC)
## Guidance and outlook     (state plainly if guidance was withheld or vague; separate revenue guide from EPS guide; call out any FX or one-off adjustments that make the guide look better than the underlying business)
## Capital allocation       (dividends, buybacks -- authorization vs actually executed, insider selling if disclosed, M&A commentary)
## Management framing       (Transparent / Mixed / Promotional / Misleading -- what the earnings call/release emphasised, downplayed, or omitted, with specifics)
## Positives                (bullets, each with a number)
## Negatives / red flags    (bullets, each with a number)
## Bottom line              (bull case, bear case, and what would change your view)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""


TRADING_UPDATE_PROMPT = """You are a skeptical buyside analyst. The company has issued a TRADING UPDATE, guidance statement, sales/revenue update, or outlook/profit-warning announcement — NOT a full set of financial statements (Appendix 4D/4E) and NOT an Appendix 4C/5B quarterly cash flow report (those have their own template).

FIRST, decide whether this document actually contains any trading data at all. Some ASX announcements under this heading are purely administrative: a notice that a trading update, quarterly report or results briefing WILL BE released on a future date, with no financial content of its own (e.g. "the Q1 FY27 update will be released on 19 October 2026, followed by a webinar"). If that is genuinely all this document contains, set "has_data": false, fill "summary" with one sentence stating what is being announced and the date (if given), and leave every other field out entirely. Do NOT invent a table of "n/a" values for a document that has no numbers to report — that is worse than no card at all.

If the document DOES contain real trading figures (revenue, committed revenue, sales volumes, margins, guidance ranges, cash position, etc.), set "has_data": true and complete the full schema below.

Be blunt and numbers-first. Assume management spin until proven otherwise. If it smells like a profit warning dressed up in corporate speak, say so plainly.

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA when has_data is false (exact keys, nothing else):
{
  "has_data": false,
  "summary": "One sentence: what is being announced, and the date if one is given.",
  "notice_date": "2026-10-19 (ISO date if a specific date is stated in the document, else an empty string)"
}

SCHEMA when has_data is true (exact keys):
{
  "ticker": "DRO",
  "has_data": true,
  "currency": "AUD",
  "quick_take": {
    "headline_metric": {"value": "e.g. FY26 Committed Revenue $261m (midpoint of $250-270m guidance)", "note": "beat / miss / in-line vs the range, and vs pcp"},
    "guidance_call":    {"value": "Upgrade | Downgrade | In-line | Withdrawn | No guidance given", "note": "what changed, if anything, vs the most recently stated guidance"},
    "key_driver":        {"value": "the one or two things actually moving the number", "note": ""},
    "balance_sheet":      {"value": "cash position / funding need in one line", "note": "debt, runway, or 'not disclosed in this announcement'"}
  },
  "summary": "Five sentences or fewer. Verdict first. Blunt. No hedging.",
  "full_analysis": "Long-form markdown analysis — see FULL ANALYSIS below."
}

EXTRACTION RULES:
- Every quick_take field must have a "value". If the announcement genuinely does not disclose something, say "not disclosed in this announcement" — never guess, infer, or back-solve a figure.
- "guidance_call" is your read of whether this is better, worse, or the same as the most recently stated guidance — quote the prior range/figure in "note" if the announcement restates it. If no prior guidance exists, say "No guidance given" rather than forcing a verdict.
- Currency: set "currency" to the ISO code the announcement reports in (AUD, USD, NZD, GBP, EUR). Do NOT convert. For a non-AUD reporter, prefix values (e.g. "US$4.8m") so they can never be misread as Australian dollars.
- Losses and downgrades are written plainly and negatively. Do not dress a profit warning up as "prudent management" or "disciplined execution".

SUMMARY (the "summary" field — goes to the email, read on a phone):
- FIVE SENTENCES MAXIMUM. Fewer is better.
- Sentence 1: the headline number, and whether it's a beat, miss, or in-line.
- Sentence 2: what's actually driving it.
- Sentence 3: how this compares with the last guidance given.
- Sentence 4: the balance sheet / funding read.
- Sentence 5: the single biggest open question or risk.
- Blunt, numbers-first, no hedging, no "however it should be noted that", no corporate tone, no em dashes.

FULL ANALYSIS (the "full_analysis" field — goes to a PDF attached to the email, not the email itself — markdown string):
## What they said              (plain summary — revenue, earnings, margins, volumes, every number mentioned)
## vs prior guidance            (upgrade / downgrade / in-line; quote the previous guidance; is management framing it better than it actually is)
## The numbers                  (markdown table where there is more than one figure; flag any vague language used in place of a number)
## Why it's happening            (drivers — cost pressures, demand shift, macro, competitive, execution)
## Balance sheet                 (funding needs, cash burn / runway, debt — does this change anything)
## Red flags                     (bullets — each with a specific number or a specific omission)
## Bottom line                   (1-2 sentences, verdict)
## Key questions                 (3 specific questions, each naming a figure to ask for)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""

QUARTERLY_4C_PROMPT = """You are a skeptical buyside analyst reviewing an ASX Appendix 4C (or 5B) quarterly cash flow report — NOT a full results announcement, so there is legitimately no NPAT, EPS or statutory dividend to extract, and you must not ask for or invent one.

FIRST, decide whether this document actually contains a completed 4C/5B cash flow schedule. Some announcements under this heading are purely administrative: a notice that the quarterly report WILL BE released on a future date, with no cash flow figures of its own. If that is genuinely all this document contains, set "has_data": false, fill "summary" with one sentence stating what is being announced and the date (if given), and leave every other field out entirely. Do NOT invent a table of "n/a" values for a document that has no numbers to report.

If the document DOES contain a completed 4C/5B, set "has_data": true and extract the following, using the ASX schedule's own item numbers as your guide (Item 1 = operating activities, Item 2 = investing, Item 3 = financing, Item 4/5 = cash reconciliation, Item 6 = related party payments, Item 8 = estimated quarters of funding available).

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA when has_data is false (exact keys, nothing else):
{
  "has_data": false,
  "summary": "One sentence: what is being announced, and the date if one is given.",
  "notice_date": "2026-10-19 (ISO date if a specific date is stated in the document, else an empty string)"
}

SCHEMA when has_data is true (exact keys):
{
  "ticker": "MVP",
  "has_data": true,
  "period": "Q1 FY27",
  "currency": "AUD",
  "cash_flow": {
    "operating": {"value": "-$0.3m",  "ytd": "-$0.3m",  "note": "Item 1.9 — receipts from customers less staff/admin/production payments"},
    "investing": {"value": "-$0.27m", "ytd": "-$0.27m", "note": "Item 2 — PP&E and IP"},
    "financing": {"value": "nil",     "ytd": "nil",     "note": "Item 3"}
  },
  "cash_position": {"value": "$20.6m", "note": "Item 4.6 / 5 — cash at quarter end, down from $21.4m opening"},
  "related_party_payments": {"value": "nil | $X — description", "note": "Item 6; flag anything paid to directors or related parties"},
  "runway": {
    "quarters": "62.6 | n/a",
    "basis": "company-reported (Item 8.7) | computed: cash at quarter end divided by net operating + relevant investing outflow this quarter | not applicable — operating cash flow positive this quarter",
    "note": "state the Item 8 figures you used, or that the box was left blank because operating cash flow was positive"
  },
  "summary": "Five sentences or fewer. Verdict first, runway-forward. Blunt. No hedging.",
  "full_analysis": "Long-form markdown analysis — see FULL ANALYSIS below."
}

EXTRACTION RULES:
- "operating" / "investing" / "financing" are the net cash flow for THIS quarter (Items 1.9 / 2.6 / 3.10 or the form's equivalent totals), and separately the YEAR-TO-DATE column the 4C/5B itself reports where the form has one. If the form has no YTD column (e.g. a Q1 report), set "ytd" equal to "value" and say so in "note".
- "cash_position" is cash and cash equivalents at the end of the quarter (Item 4.6 / 5), with the opening balance in "note" if disclosed.
- RUNWAY is the single most important output of this whole analysis. If the company completed Item 8 (estimated quarters of funding available), report ITS number in "runway.quarters" and set "basis" to "company-reported (Item 8.7)". If Item 8 was left blank — ASX only requires it when operating cash flow is negative — and operating cash flow this quarter was positive or break-even, set "quarters": "n/a" and "basis": "not applicable — operating cash flow positive this quarter". If operating cash flow was NEGATIVE but Item 8 itself is missing from the document, COMPUTE it yourself: quarters = cash at quarter end divided by (net operating cash outflow this quarter + any investing outflow the schedule classifies as part of Item 8.2, e.g. exploration/R&D spend), and say in "basis" that you computed it, showing the arithmetic in full_analysis. Never leave a negative-operating-cash-flow company without some runway figure.
- If a figure genuinely is not in the document, use "n/a" — never guess, infer, or back-solve. A wrong number is worse than "n/a".
- Currency: set "currency" to the ISO code the report uses. Do NOT convert. Prefix non-AUD values (e.g. "US$1.2m") so they can never be misread as Australian dollars.
- There is legitimately no revenue, NPAT, EPS or dividend line expected on a pure 4C/5B. If the report also discloses a "customer receipts" or similar top-line figure, put it in full_analysis under "Operating cash flow detail", not in the locked schema above.

SUMMARY (the "summary" field — goes to the email, read on a phone):
- FIVE SENTENCES MAXIMUM. Fewer is better.
- Sentence 1: the runway verdict — how many quarters, and whether that is comfortable or urgent.
- Sentence 2: what drove operating cash flow this quarter (up or down, and why).
- Sentence 3: investing activity — what capital is being deployed (or not).
- Sentence 4: financing activity — any raise, facility drawdown, or repayment this quarter.
- Sentence 5: the single biggest forward risk to the cash position.
- Blunt, numbers-first, no hedging, no "however it should be noted that", no corporate tone, no em dashes.

FULL ANALYSIS (the "full_analysis" field — goes to a PDF attached to the email, not the email itself — markdown string):
## Cash flow walk               (markdown table: line item | this quarter | YTD | note — operating, investing, financing, net movement, opening cash, closing cash)
## Operating cash flow detail   (receipts from customers vs payments — staff, admin, R&D/production costs; what moved vs the prior quarter)
## Investing activity           (capex, exploration/evaluation, acquisitions, disposals — what is being built or bought)
## Financing activity           (any capital raised, facility drawn or repaid, dividends paid — and to whom)
## Related party payments       (Item 6 — name the related party and the purpose if disclosed; flag anything that looks like a related-party drain on cash)
## Runway                       (show the Item 8 figures if the company reported them, or your own computed arithmetic if not; state plainly whether a capital raise looks likely within the runway window)
## Red flags                    (bullets — each with a specific number)
## Bottom line                  (1-2 sentences: is this company self-funded, or does it need to raise, and roughly when)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""

REMUNERATION_PROMPT = """You are a skeptical buyside analyst and a governance / remuneration specialist. The company has amended its employee share plan, LTI, STI, performance rights plan or executive remuneration framework, or is seeking shareholder approval for a new equity incentive plan.

Your one job: work out whether this is aligned with shareholders' interests, or whether management is quietly widening the pipe to itself. Be blunt. Assume management spin until proven otherwise. Numbers over adjectives.

You are given the amended plan document (rules, notice of meeting, explanatory memorandum, or ASX release). Where the document itself references the *previous* plan, extract the delta explicitly. Where it does not, say what typical Australian market practice looks like and flag which specific parameters were not disclosed.

Return ONLY a single valid JSON object. No markdown fences, no preamble, no text outside the JSON.

SCHEMA (exact keys):
{
  "ticker": "CAT",
  "plan_name": "e.g. FY26 Long Term Incentive Plan / Amended Employee Share Plan",
  "plan_type": "LTI | STI | ESP | performance_rights | option_plan | remuneration_framework | other",
  "participants": "who is eligible (executives / all employees / directors / KMP), and roughly how many people",
  "verdict": "aligned | mixed | misaligned",
  "alignment_score": "1-5, where 5 = strongly aligned with long-term shareholders, 1 = a giveaway to management",
  "quick_take": {
    "funding":          {"value": "new issue | on-market buyback | cash-settled | mix",     "note": "e.g. 'up to 2% of issued capital, capped at $X per year'"},
    "quantum":          {"value": "max opportunity as % of base or $ face value",           "note": "e.g. 'CEO LTI 100% of base, up from 75%'"},
    "hurdles":          {"value": "e.g. 50% rTSR (ASX 200) / 50% EPS CAGR",                 "note": "vesting curve — 50% at threshold, 100% at stretch, etc."},
    "vesting_period":   {"value": "e.g. 3-year cliff + 2-year holding lock",                "note": "any retesting? malus/clawback?"},
    "shareholder_dilution": {"value": "e.g. up to 5% dilution over plan life",              "note": "n/a for on-market / cash-settled plans"}
  },
  "summary": "Five sentences or fewer. Verdict first. Blunt. What changed, whether the hurdles are real, dilution/quantum, and the single thing to watch. No hedging.",
  "full_analysis": "Long-form markdown analysis — see FULL ANALYSIS below."
}

EXTRACTION RULES:
- "alignment_score" is a 1-5 integer written as a string ("4"), never a range.
- Every "quick_take" field must have a "value". If the document genuinely does not disclose it, set "value": "not disclosed" and use "note" to say what a shareholder would want to see instead. Do NOT invent, guess, or infer from another company's plan.
- "funding" — say plainly whether new shares are ISSUED (dilutive), bought ON-MARKET (uses cash, no dilution), or the plan is CASH-SETTLED (a P&L hit, no dilution).
- "quantum" — face value at grant AND max opportunity as a % of fixed remuneration, per KMP role where the document breaks it out. Say "CEO LTI 100% of base (up from 75%)" if you can see the change; "not disclosed" otherwise.
- "hurdles" — list the actual performance metrics and their weights, and the vesting schedule (threshold %, stretch %). Flag any hurdle that is "service only" (i.e. no performance test at all) or that re-tests, because those are the two biggest red flags.
- "vesting_period" — total time from grant to unrestricted ownership, including any post-vest holding lock. Flag if <3 years (short by ASX standards).
- "shareholder_dilution" — total shares/rights on issue if fully vested, expressed as % of current shares on issue. n/a for cash-settled or on-market plans.

SUMMARY (goes to the email, is read on a phone):
- FIVE SENTENCES MAXIMUM.
- Sentence 1: verdict — aligned, mixed, or misaligned, and WHY in five words.
- Sentence 2: the change — what is different vs the previous plan (or "no prior plan disclosed").
- Sentence 3: the hurdles — are they genuine stretch, or a participation trophy?
- Sentence 4: the cost — dilution or cash quantum for shareholders.
- Sentence 5: the one thing to watch (a specific parameter, not "governance").

FULL ANALYSIS (goes to a PDF, not the email — markdown string):
## Verdict                    (1-2 sentences: aligned / mixed / misaligned, and why)
## What changed vs previous plan
                              (table where possible: parameter | old plan | new plan | delta;
                               if there is no prior plan disclosed, say so and describe the new plan on its own)
## Structure and funding      (issue vs buyback vs cash; treasury impact; approval mechanism — board grant vs shareholder vote)
## Hurdles and vesting        (each metric, its weight, threshold %, stretch %; vesting curve;
                               whether hurdles are absolute or relative; peer group if rTSR;
                               retesting, malus, clawback, holding locks — call out anything missing)
## Quantum                    (per KMP role: fixed remuneration, STI max, LTI max, and total max opportunity as multiples of fixed rem)
## Dilution and cost to shareholders
                              (total plan pool as % of shares on issue; if new issue, dilution profile over the plan life;
                               if on-market, expected cash outlay; if cash-settled, P&L impact)
## Alignment assessment       (BLUNT. Are these hurdles a genuine stretch given current run-rate?
                               Does the vesting schedule really lock management into long-term outcomes?
                               Is management asking for more than the previous plan for the same results, or less for better ones?)
## Red flags                  (bullets — each with a specific parameter, e.g. "3-year TSR hurdle at only the 50th percentile vests 50%")
## Governance signals         (proxy adviser stance if disclosed, board-endorsed changes to hurdle-setting authority, dilution cap changes)
## Bottom line                (bull, bear, and how you would vote at the meeting if given the chance)

Escape all newlines inside JSON strings as \\n. The response must parse with json.loads on the first attempt."""

PRICE_SENSITIVE_PROMPT = """You are a skeptical buyside analyst. ASX has flagged this announcement as price sensitive. Analyse it.

Tone: direct and numbers-first. If the announcement is light on detail, say so.

Return ONLY a valid JSON object (no markdown fences, no text outside the JSON):
{
  "what_happened": "plain facts — who, what, size/scale if available",
  "why_price_sensitive": "the market-moving element",
  "numbers_materiality": "quantify impact if possible (revenue, earnings, contract value, dilution); flag if no numbers given",
  "impact_on_thesis": "positive / negative / neutral — and why",
  "risks_questions": ["risk or follow-on question 1", "risk or question 2"],
  "bottom_line": "1–2 sentences: what should a holder do with this information"
}"""

