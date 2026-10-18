"""The forwardable PDF behind each Micky's Macro email -- same split every
other agent in this repo uses (Bob's native Doc, Slinger's/Harry's
attached PDF): the email is a glance, this PDF is the analysis. Rendered
with weasyprint (same engine Bob/Harry use), which runs fine on
``ubuntu-latest`` -- no self-hosted Windows runner needed, unlike
Slinger's Playwright+Chrome PDF.

The email may use only inline styles (mail clients strip ``<style>``
blocks); a PDF has no such constraint, so this module uses one real
stylesheet (``PDF_CSS``, adapted from Harry's) for a document that
actually looks like a report rather than a chain of inline-styled
``<div>``s.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

from .schemas import CompanyCandidate, EmailRecord, ExtractedClaim, TrendDossier, TrendScore

esc = _html.escape

PDF_CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm;
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font-family: 'Segoe UI', Roboto, Arial, sans-serif; font-size: 8pt; color: #6B7280; }
  @bottom-left { content: "Micky's Macro"; font-family: 'Segoe UI', Roboto, Arial, sans-serif; font-size: 8pt; color: #6B7280; } }
body { font-family: 'Segoe UI', Roboto, Arial, sans-serif; font-size: 10pt; line-height: 1.5; color: #1F2937; }
.cover { background: #1E3A8A; color: #fff; padding: 16pt 18pt; border-radius: 6pt; }
.cover .kicker { font-size: 8pt; letter-spacing: 2pt; color: #BFDBFE; font-weight: 700; text-transform: uppercase; }
.cover h1 { font-size: 22pt; margin: 4pt 0 2pt 0; }
.cover .sub { color: #BFDBFE; font-size: 10pt; }
.pill { display: inline-block; padding: 2pt 7pt; border-radius: 4pt; font-size: 8pt; font-weight: 800; letter-spacing: 0.4pt; }
h2 { font-size: 13pt; color: #1E3A8A; border-bottom: 2px solid #BFDBFE; padding-bottom: 3pt; margin: 18pt 0 8pt 0; page-break-after: avoid; }
h3 { font-size: 11pt; color: #1E3A8A; margin: 10pt 0 4pt 0; page-break-after: avoid; }
table.keys { width: 100%; border-collapse: collapse; margin: 8pt 0 12pt; }
table.keys td { padding: 5pt 9pt; border-bottom: 1px solid #E5E7EB; font-size: 9.5pt; }
table.keys td.v { text-align: right; font-weight: 700; }
table.keys tr:nth-child(odd) td { background: #F3F4F8; }
table.scorecard { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 8.8pt; }
table.scorecard th { background: #1E3A8A; color: #fff; text-align: left; padding: 5pt 6pt; }
table.scorecard td { border: 1px solid #E5E7EB; padding: 5pt 6pt; vertical-align: top; }
.dossier-block { border: 1px solid #E5E7EB; border-radius: 6pt; padding: 10pt 12pt; margin: 8pt 0 14pt; page-break-inside: avoid; }
.dossier-block .ticker-row { font-weight: 800; color: #1E3A8A; font-size: 12pt; }
.chain { list-style: none; padding: 0; margin: 4pt 0; }
.chain li { margin: 0 0 4pt 0; padding-left: 10pt; border-left: 2pt solid #BFDBFE; font-size: 9.5pt; }
ul.plain { margin: 4pt 0 8pt 14pt; padding: 0; font-size: 9.5pt; }
ul.plain li { margin: 0 0 3pt 0; }
.callout { border-left: 4pt solid #1E3A8A; background: #EFF6FF; padding: 9pt 12pt; margin: 8pt 0; page-break-inside: avoid; font-size: 9.5pt; }
.filter-row { margin: 4pt 0; font-size: 9.5pt; }
.filter-row b { color: #1E3A8A; }
.muted { color: #6B7280; font-size: 8.5pt; }
.small { font-size: 8pt; color: #6B7280; }
.claim-fact { color: #065F46; font-weight: 700; }
.claim-forecast { color: #1D4ED8; font-weight: 700; }
.claim-opinion { color: #92400E; font-weight: 700; }
.claim-inference { color: #6D28D9; font-weight: 700; }
.disclaimer { margin-top: 18pt; font-size: 8pt; color: #6B7280; border-top: 1px solid #E5E7EB; padding-top: 6pt; }
"""

_CLAIM_CLASS = {"FACT": "claim-fact", "FORECAST": "claim-forecast", "OPINION": "claim-opinion", "INFERENCE": "claim-inference"}

_DISCLAIMER = (
    "Research and decision support only. Micky's Macro never buys, sells or resizes anything -- every "
    "investment decision stays with you. An attractive macro trend, an attractive industry, an attractive "
    "company and an attractive investment at today's price are four different conclusions; this document "
    "keeps them separate on purpose. Claim tags: Fact (verifiable, author-stated), Forecast (author's own "
    "prediction), Opinion (author's view), Inference (Micky's Macro's own addition, explicitly marked as such "
    "-- never presented as the source's claim). Valuation figures come from EODHD; a coverage gap is shown "
    "as such, never estimated."
)


def _doc(title: str, body: str) -> str:
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<style>{PDF_CSS}</style></head><body>{body}"
        f"<div class='disclaimer'>{esc(_DISCLAIMER)}</div></body></html>"
    )


def _cover(kicker: str, title: str, subtitle: str) -> str:
    return (
        f"<div class='cover'><div class='kicker'>{esc(kicker)}</div>"
        f"<h1>{esc(title)}</h1><div class='sub'>{esc(subtitle)}</div></div>"
    )


def _list(items: list[str]) -> str:
    if not items:
        return "<p class='muted'>None recorded.</p>"
    return "<ul class='plain'>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def _or_muted(text: str, label: str = "not yet filled in") -> str:
    """*text*, escaped, or a muted placeholder span if empty. Built outside
    any f-string's ``{}`` on purpose: Python 3.11 (the Actions runner)
    rejects a backslash-escaped quote inside an f-string expression part,
    which an inline ``'<span class=\\"muted\\">...'`` fallback would need."""
    return esc(text) if text else f"<span class='muted'>{esc(label)}</span>"


def _dossier_full_html(d: TrendDossier) -> str:
    return (
        f"<div class='dossier-block'>"
        f"<div class='ticker-row'>{esc(d.name)}</div>"
        f"<div class='small'>{esc(d.category)} &middot; {esc(d.secular_or_cyclical)} &middot; confidence {esc(d.confidence)} "
        f"&middot; last reviewed {esc(d.last_reviewed[:10])}</div>"
        f"<p>{esc(d.thesis)}</p>"
        f"<h3>What's changing and why</h3><p>{_or_muted(d.what_changing_and_why)}</p>"
        f"<table class='keys'>"
        f"<tr><td>Expected duration</td><td class='v'>{esc(d.expected_duration) or 'n/a'}</td></tr>"
        f"<tr><td>Adoption curve</td><td class='v'>{esc(d.adoption_curve) or 'n/a'}</td></tr>"
        f"<tr><td>Capex &amp; financing</td><td class='v'>{esc(d.capex_and_financing) or 'n/a'}</td></tr>"
        f"</table>"
        f"<h3>Demand drivers</h3>{_list(d.demand_drivers)}"
        f"<h3>Supply constraints &amp; bottlenecks</h3>{_list(d.supply_constraints)}"
        f"<h3>Policy &amp; geopolitical dependencies</h3>{_list(d.policy_and_geopolitics)}"
        f"<h3>Winners / losers / disrupted models</h3>"
        f"<table class='keys'><tr><td>Winners</td><td class='v'>{esc(', '.join(d.winners) or 'none yet')}</td></tr>"
        f"<tr><td>Losers</td><td class='v'>{esc(', '.join(d.losers) or 'none yet')}</td></tr>"
        f"<tr><td>Disrupted business models</td><td class='v'>{esc(', '.join(d.disrupted_business_models) or 'none yet')}</td></tr></table>"
        f"<h3>First / second / third order consequences</h3>"
        f"{_list(d.first_order_consequences)}{_list(d.second_order_consequences)}{_list(d.third_order_consequences)}"
        f"<h3>Evidence for</h3>{_list(d.evidence_for)}"
        f"<h3>Evidence against</h3>{_list(d.evidence_against)}"
        f"<div class='callout'><b>What would invalidate this thesis:</b>{_list(d.invalidation_criteria)}</div>"
        f"<h3>Leading indicators</h3>{_list(d.leading_indicators)}"
        f"<div class='small'>Linked companies: {esc(', '.join(d.linked_companies) or 'none yet')}</div>"
        f"</div>"
    )


def _candidate_full_html(c: CompanyCandidate) -> str:
    v = c.valuation
    val_rows = (
        f"<tr><td>Price</td><td class='v'>{esc(f'{v.price} {v.currency}') if v.price is not None else 'n/a'}</td></tr>"
        f"<tr><td>P/E (trailing)</td><td class='v'>{f'{v.pe:.1f}x' if v.pe is not None else 'n/a'}</td></tr>"
        f"<tr><td>Forward P/E</td><td class='v'>{f'{v.forward_pe:.1f}x' if v.forward_pe is not None else 'n/a'}</td></tr>"
        f"<tr><td>EV/EBITDA</td><td class='v'>{f'{v.ev_ebitda:.1f}x' if v.ev_ebitda is not None else 'n/a'}</td></tr>"
        f"<tr><td>Dividend yield</td><td class='v'>{f'{v.dividend_yield_pct:.1f}%' if v.dividend_yield_pct is not None else 'n/a'}</td></tr>"
        f"<tr><td>FCF yield</td><td class='v'>{f'{v.fcf_yield_pct:.1f}%' if v.fcf_yield_pct is not None else 'n/a'}</td></tr>"
    )
    if v.not_covered_reason:
        val_rows += f"<tr><td>Coverage</td><td class='v'>{esc(v.not_covered_reason)}</td></tr>"
    filt = c.investment_filter
    return (
        f"<div class='dossier-block'>"
        f"<div class='ticker-row'>{esc(c.ticker)} ({esc(c.exchange) or 'n/a'})" + (f" &mdash; {esc(c.name)}" if c.name else "") + "</div>"
        f"<div class='small'>{esc(c.exposure_type.replace('_', ' ').title())}</div>"
        f"<p><b>Why now:</b> {esc(c.why_now)}</p>"
        f"<h3>Macro &rarr; company causal chain</h3><ul class='chain'>{''.join(f'<li>{esc(s)}</li>' for s in c.causal_chain)}</ul>"
        f"<h3>Competitive advantage</h3><p>{_or_muted(c.competitive_advantage)}</p>"
        f"<h3>Current valuation (EODHD, never estimated)</h3><table class='keys'>{val_rows}</table>"
        f"<h3>Investment filter</h3>"
        f"<div class='filter-row'><b>Macro attractiveness.</b> {esc(filt.macro_attractiveness)}</div>"
        f"<div class='filter-row'><b>Industry economics.</b> {esc(filt.industry_economics)}</div>"
        f"<div class='filter-row'><b>Company quality.</b> {esc(filt.company_quality)}</div>"
        f"<div class='filter-row'><b>Valuation and prospective return.</b> {esc(filt.valuation_and_prospective_return)}</div>"
        f"<div class='filter-row'><b>Portfolio suitability.</b> {esc(filt.portfolio_suitability)}</div>"
        f"<h3>Main risks</h3>{_list(c.key_risks)}"
        f"<h3>Portfolio &amp; watchlist overlap</h3><p>{_or_muted(', '.join(c.portfolio_overlap), 'none found')}</p>"
        f"<h3>Further work needed before a decision</h3>{_list(filt.further_work_needed)}"
        f"</div>"
    )


def _scorecard_table_html(score: TrendScore | None) -> str:
    if score is None:
        return "<p class='muted'>Not yet scored.</p>"
    dims = [
        ("Structural demand strength", score.structural_demand_strength),
        ("Expected duration", score.expected_duration),
        ("Supply scarcity", score.supply_scarcity),
        ("Evidence quality", score.evidence_quality),
        ("Monetisation visibility", score.monetisation_visibility),
        ("Industry economics", score.industry_economics),
        ("Investable company availability", score.investable_company_availability),
        ("Valuation attractiveness", score.valuation_attractiveness),
        ("Portfolio diversification", score.portfolio_diversification),
        ("Consensus / crowding risk", score.consensus_crowding_risk),
    ]
    rows = "".join(
        f"<tr><td>{esc(label)}</td><td style='text-align:center;font-weight:800'>{dim.score}/10</td>"
        f"<td>{esc(dim.rationale)}</td><td class='muted'>{esc(dim.uncertainty)}</td></tr>"
        for label, dim in dims
    )
    return (
        "<table class='scorecard'><tr><th>Dimension</th><th>Score</th><th>Rationale</th><th>Uncertainty</th></tr>"
        f"{rows}</table>"
    )


def _email_claims_html(e: EmailRecord, claims: list[ExtractedClaim]) -> str:
    rows = "".join(
        f"<li><span class='{_CLAIM_CLASS.get(c.claim_type, '')}'>{esc(c.claim_type)}</span> {esc(c.text)}"
        + (f" <span class='muted'>(companies: {esc(', '.join(c.companies))})</span>" if c.companies else "")
        + "</li>"
        for c in claims
    )
    link = f"<div class='small'><a href='{esc(e.gmail_link)}'>Open in Gmail</a></div>" if e.gmail_link else ""
    return (
        f"<div class='dossier-block'><div class='ticker-row'>{esc(e.subject or '(no subject)')}</div>"
        f"<div class='small'>{esc(e.source_name)} &middot; {esc(e.received_at[:10])}</div>"
        f"<ul class='plain'>{rows}</ul>{link}</div>"
    )


# ---------------------------------------------------------------------------
# Public builders -- one per email type in reports.py
# ---------------------------------------------------------------------------

def build_daily_brief_pdf_html(inp) -> str:
    body = _cover("MICKY'S MACRO -- DAILY BRIEF", inp.run_date,
                  f"{inp.emails_processed} new research email(s), {inp.emails_skipped_duplicate} already seen")
    if inp.updated_dossiers:
        body += "<h2>New or changed macro theses</h2>" + "".join(_dossier_full_html(d) for d in inp.updated_dossiers)
    if inp.new_candidates:
        body += "<h2>New investable opportunities</h2>" + "".join(_candidate_full_html(c) for c in inp.new_candidates)
    if inp.contradicting_evidence:
        body += "<h2>Evidence against an existing thesis</h2>" + _list(inp.contradicting_evidence)
    if inp.portfolio_notes:
        body += "<h2>Portfolio &amp; watchlist implications</h2>" + _list(inp.portfolio_notes)
    if inp.next_indicators:
        body += "<h2>Next indicators to watch</h2>" + _list(inp.next_indicators)
    return _doc(f"Micky's Macro Daily Brief {inp.run_date}", body)


def build_weekly_review_pdf_html(inp) -> str:
    body = _cover("MICKY'S MACRO -- WEEKLY INVESTMENT REVIEW", f"Week ending {inp.week_ending}",
                  "Ten independent scores per trend -- never averaged into one number")
    body += "<h2>Ranked structural trends</h2>"
    for i, (d, score) in enumerate(inp.ranked):
        body += f"<h3>#{i + 1}</h3>" + _dossier_full_html(d) + _scorecard_table_html(score)
    extra = [
        ("Changes in conviction and why", inp.conviction_changes),
        ("New bottlenecks / emerging opportunities", inp.new_bottlenecks),
        ("Companies with improving investment cases", inp.improving_companies),
        ("Companies with deteriorating investment cases", inp.deteriorating_companies),
        ("Valuation and consensus concerns", inp.valuation_concerns),
        ("Cross-checks against the existing portfolio", inp.portfolio_cross_check),
        ("Most interesting opportunities to investigate next", inp.next_to_investigate),
        ("Strongest counterarguments", inp.strongest_counterarguments),
    ]
    for title, items in extra:
        if items:
            body += f"<h2>{esc(title)}</h2>" + _list(items)
    return _doc(f"Micky's Macro Weekly Review {inp.week_ending}", body)


def build_company_opportunity_pdf_html(candidate: CompanyCandidate, dossier: TrendDossier) -> str:
    body = _cover("MICKY'S MACRO -- COMPANY OPPORTUNITY BRIEF", candidate.ticker, dossier.name)
    body += "<h2>Trend context</h2>" + _dossier_full_html(dossier)
    body += "<h2>Company candidate</h2>" + _candidate_full_html(candidate)
    return _doc(f"Micky's Macro -- {candidate.ticker}", body)


def build_gmail_digest_pdf_html(emails: list[EmailRecord], claims_by_email: dict[str, list[ExtractedClaim]]) -> str:
    body = _cover("MICKY'S MACRO -- GMAIL RESEARCH DIGEST", f"{len(emails)} new item(s)",
                  "Citrini Research, Ray Dalio / Economic Principles, Scott Galloway / Prof G, Chamath Palihapitiya")
    body += "".join(_email_claims_html(e, claims_by_email.get(e.id, [])) for e in emails)
    return _doc("Micky's Macro Gmail Research Digest", body)


def render_pdf(html: str, path: Path) -> Path:
    """Render with weasyprint (same engine as Bob/Harry). Raises ImportError
    if it isn't installed -- the caller decides whether that's fatal."""
    from weasyprint import HTML

    path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html).write_pdf(str(path))
    return path
