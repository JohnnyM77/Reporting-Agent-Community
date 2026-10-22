# mike/report.py
#
# Outputs, in Bob's house style:
#   * a PDF report (weasyprint, same engine as Harry) that opens every company
#     with the framework's standard scorecard (section 10) and keeps the
#     audit trail Raw evidence -> Calculation -> Base -> Overlay -> Final
#     (section 8.8), the workpaper, the Market Position evidence register and
#     the QA/QC certification;
#   * a phone-first email: dark outer panel, white cards with a green header
#     bar, table-only HTML with inline styles (no <style>, class=, flex, grid).
#
# The PDF is the one place a <style> block is allowed (the email rule is an
# email-client limit, not a PDF one).

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
from typing import Optional

from mike.assess import ORDER, Assessment
from mike.rubric import money, pct

esc = html.escape

# Bob's palette (agent.py)
NAVY = "#0B1220"
PANEL = "#111B2E"
GREEN = "#14532D"
GREEN_SUB = "#A7F3D0"
SHADE = "#F1F5F2"
LABEL = "#374151"
VALUE = "#111827"
MUTED = "#6B7280"
RED = "#B91C1C"
AMBER = "#B45309"
OK = "#15803D"
FONT = "Arial, Helvetica, sans-serif"

CLASS_COLOUR = {"High": "#15803D", "Medium-High": "#4D7C0F", "Medium": "#B45309", "Low": "#C2410C",
                "Very Low": "#B91C1C", "n/a": "#6B7280"}
SHORT = {"stability": "Stab", "quality": "EQ", "market": "Mkt", "balance": "BS", "returns": "ROC", "growth": "Grow"}
TREND_COLOUR = {"Improving": "#15803D", "Stable": "#6B7280", "Deteriorating": "#B91C1C"}
STATUS_COLOUR = {"PASS": "#15803D", "DRAFT": "#B45309", "NOT SCORED": "#B91C1C"}


def s(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def overall_text(a: Assessment) -> str:
    if a.overall is None:
        return "n/a"
    return f"{a.overall:.2f}" + (" (provisional)" if a.provisional else "")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

CSS = f"""
@page {{ size: A4; margin: 16mm 14mm 16mm 14mm;
  @bottom-left {{ content: "Mike | Stock Quality Assessment Framework v3.1 (Mikebrisy) | EODHD statutory data"; font: 7.5pt {FONT}; color: {MUTED}; }}
  @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font: 7.5pt {FONT}; color: {MUTED}; }} }}
body {{ font-family: {FONT}; font-size: 9pt; color: {VALUE}; line-height: 1.35; }}
h1 {{ font-size: 20pt; margin: 0 0 2mm; color: #FFFFFF; }}
h2 {{ font-size: 13pt; margin: 0; color: #FFFFFF; }}
h3 {{ font-size: 10.5pt; margin: 5mm 0 2mm; color: {GREEN}; border-bottom: 1.5px solid {GREEN}; padding-bottom: 1mm; }}
.cover {{ background: {NAVY}; color: #FFFFFF; padding: 8mm 8mm 6mm; border-radius: 3mm; }}
.cover p {{ color: #CBD5E1; margin: 1mm 0; }}
.bar {{ background: {GREEN}; color: #FFFFFF; padding: 4mm 5mm; border-radius: 2mm; page-break-after: avoid; }}
.bar .sub {{ color: {GREEN_SUB}; font-size: 8.5pt; margin-top: 1mm; }}
.company {{ page-break-before: always; }}
table {{ width: 100%; border-collapse: collapse; margin: 2mm 0; page-break-inside: auto; }}
tr {{ page-break-inside: avoid; }}
th {{ background: {SHADE}; color: {LABEL}; text-align: left; font-size: 8pt; padding: 1.6mm 2mm; border-bottom: 1px solid #D1D5DB; }}
td {{ padding: 1.6mm 2mm; border-bottom: 1px solid #E5E7EB; vertical-align: top; font-size: 8.5pt; }}
td.num, th.num {{ text-align: right; white-space: nowrap; }}
tr.total td {{ font-weight: bold; background: {SHADE}; }}
.pill {{ display: inline-block; padding: 0.6mm 2mm; border-radius: 1.5mm; color: #FFFFFF; font-weight: bold; font-size: 8pt; }}
.note {{ color: {MUTED}; font-size: 8pt; }}
.warn {{ border: 1px solid #FCA5A5; background: #FEF2F2; color: {RED}; padding: 2.5mm 3mm; border-radius: 1.5mm; margin: 2mm 0; }}
.amber {{ border: 1px solid #FCD34D; background: #FFFBEB; color: {AMBER}; padding: 2.5mm 3mm; border-radius: 1.5mm; margin: 2mm 0; }}
.small {{ font-size: 7.5pt; }}
"""


def pill(text: str, colour: str) -> str:
    return f'<span class="pill" style="background:{colour}">{esc(text)}</span>'


def _summary_table(assessments: list[Assessment]) -> str:
    rows = []
    ranked = sorted(assessments, key=lambda a: -(a.overall if a.overall is not None else -1))
    for a in ranked:
        crit = "".join(f'<td class="num">{s(a.criteria[k].final) if a.criteria else "n/a"}</td>' for k in ORDER)
        risks = ", ".join(SHORT[k] for k, c in a.criteria.items() if c.final is not None and c.final <= 1.0) or ""
        rows.append(
            f"<tr><td><b>{esc(a.ticker)}</b><br><span class='note'>{esc(a.name)}</span></td>{crit}"
            f"<td class='num'><b>{esc(overall_text(a))}</b></td>"
            f"<td>{pill(a.classification, CLASS_COLOUR.get(a.classification, MUTED))}</td>"
            f"<td style='color:{TREND_COLOUR.get(a.trend, MUTED)}'><b>{esc(a.trend)}</b></td>"
            f"<td>{pill(a.status, STATUS_COLOUR.get(a.status, MUTED))}</td>"
            f"<td class='small'>{esc(risks)}</td></tr>")
    head = ("<tr><th>Company</th><th class='num'>Stab</th><th class='num'>EQ</th><th class='num'>Mkt</th>"
            "<th class='num'>BS</th><th class='num'>ROC</th><th class='num'>Grow</th><th class='num'>Overall</th>"
            "<th>Class</th><th>Trend</th><th>QA/QC</th><th>Criteria &lt;= 1</th></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def _scorecard(a: Assessment) -> str:
    rows = []
    for k in ORDER:
        c = a.criteria[k]
        rows.append(f"<tr><td><b>{esc(c.name)}</b></td><td class='num'><b>{s(c.final)}</b></td>"
                    f"<td>{esc(c.period)}<br><span class='note'>{esc(c.window)}</span></td><td>{esc(c.rationale)}</td></tr>")
    rows.append(f"<tr class='total'><td>OVERALL QUALITY SCORE</td><td class='num'>{esc(overall_text(a))}</td>"
                f"<td>Arithmetic mean</td><td>{pill(a.classification, CLASS_COLOUR.get(a.classification, MUTED))}</td></tr>")
    rows.append(f"<tr class='total'><td>QUALITY TREND</td><td class='num'></td><td>Recent 2-3 years</td>"
                f"<td style='color:{TREND_COLOUR.get(a.trend, MUTED)}'>{esc(a.trend)}</td></tr>")
    rows.append(f"<tr class='total'><td>QA/QC STATUS</td><td class='num'></td><td>Pre-publication</td>"
                f"<td>{pill(a.status, STATUS_COLOUR.get(a.status, MUTED))}</td></tr>")
    return ("<table><tr><th>Criterion</th><th class='num'>Score / 5</th><th>Evidence period</th>"
            f"<th>One-line rationale</th></tr>{''.join(rows)}</table>")


def _audit_trail(a: Assessment) -> str:
    rows = []
    for k in ORDER:
        c = a.criteria[k]
        calcs = "<br>".join(f"{esc(x.name)}: <b>{esc(x.display)}</b>" + (f" <span class='note'>({esc(x.note)})</span>" if x.note else "")
                            for x in c.calcs if x.display not in ("", None))
        ovs = "<br>".join(
            f"{'+' if o.adjustment > 0 else ''}{o.adjustment:g} {esc(o.reason)} <span class='note'>[{esc(o.origin)}] {esc(o.evidence)}"
            + (f" | {esc(o.source)}" if o.source else "") + "</span>"
            + ("" if o.accepted else f" <b style='color:{RED}'>REJECTED: {esc(o.rejected_because)}</b>")
            for o in c.overlays) or "none"
        flags = "".join(f"<br><span style='color:{AMBER}'>Flag: {esc(f)}</span>" for f in c.flags)
        inap = "".join(f"<br><span class='note'>Inapplicable: {esc(i)}</span>" for i in c.inapplicable)
        rows.append(f"<tr><td><b>{esc(c.name)}</b></td><td class='small'>{calcs}{inap}</td>"
                    f"<td class='small'><b>{s(c.base)}</b><br>{esc(c.base_reason)}</td>"
                    f"<td class='small'>{ovs}{flags}</td><td class='num'><b>{s(c.final)}</b></td></tr>")
    return ("<table><tr><th>Criterion</th><th>Raw evidence and calculation</th><th>Base score</th>"
            f"<th>Overlay</th><th class='num'>Final</th></tr>{''.join(rows)}</table>")


def _workpaper(a: Assessment) -> str:
    ccy = a.currency or ""
    yrs = a.rows[-6:]
    fields = [("Revenue", "revenue"), ("EBITDA", "ebitda"), ("EBIT", "ebit"), ("PBT", "pbt"), ("NPAT (statutory)", "npat"),
              ("CFO", "cfo"), ("Capex", "capex"), ("FCF (CFO - capex)", "fcf"), ("Cash", "cash"),
              ("Gross debt incl. leases", "debt"), ("Net debt", "net_debt"), ("Equity", "equity")]
    head = "<tr><th>" + esc(ccy) + "</th>" + "".join(f"<th class='num'>{r.fy}</th>" for r in yrs) + "</tr>"
    body = ""
    for label, attr in fields:
        body += f"<tr><td>{label}</td>" + "".join(f"<td class='num'>{esc(money(getattr(r, attr)))}</td>" for r in yrs) + "</tr>"
    body += "<tr><td>EPS (statutory)</td>" + "".join(
        f"<td class='num'>{'n/a' if r.eps is None else f'{r.eps:.4f}'}</td>" for r in yrs) + "</tr>"
    body += "<tr><td>Shares on issue (m)</td>" + "".join(
        f"<td class='num'>{'n/a' if not r.shares else f'{r.shares / 1e6:,.1f}'}</td>" for r in yrs) + "</tr>"
    body += "<tr><td>EBIT margin</td>" + "".join(f"<td class='num'>{pct(r.ebit_margin, 1)}</td>" for r in yrs) + "</tr>"
    return f"<table>{head}{body}</table>"


def _register(a: Assessment) -> str:
    if not a.market_register:
        return f"<div class='amber'>Evidence register not completed: {esc(a.evidence_status)}. Market Position is unscored and the assessment stays DRAFT.</div>"
    rows = []
    for t in a.market_register:
        status = ("<b style='color:%s'>1 point</b>" % OK) if t["awarded"] else (
            f"<b style='color:{RED}'>0 (claimed, rejected: {esc(t['rejected_because'])})</b>" if t["claimed"] else "0")
        src = esc(t["source"])
        rows.append(f"<tr><td><b>{esc(t['label'])}</b></td><td>{status}</td><td class='small'>{esc(t['evidence']) or '<span class=note>No demonstrated evidence</span>'}"
                    f"{('<br><span class=note>' + esc(t['period']) + '</span>') if t['period'] else ''}</td><td class='small'>{src}</td></tr>")
    return f"<table><tr><th>Test</th><th>Result</th><th>Evidence</th><th>Source</th></tr>{''.join(rows)}</table>"


def _certification(a: Assessment) -> str:
    rows = "".join(
        f"<tr><td>{esc(r['group'])}</td><td>{esc(r['check'])}</td>"
        f"<td><b style='color:{OK if r['status'] == 'PASS' else RED if r['status'] == 'FAIL' else MUTED}'>{r['status']}</b></td>"
        f"<td class='small'>{esc(r['note'])}</td></tr>" for r in a.certification)
    return f"<table><tr><th>Control group</th><th>Check</th><th>Status</th><th>Note</th></tr>{rows}</table>"


def company_html(a: Assessment) -> str:
    sub = f"{esc(a.sector or 'Sector n/a')} | statements in {esc(a.currency or 'n/a')} | latest FY {esc(a.latest_fy)}"
    out = [f"<div class='company' id='{esc(a.ticker)}'><div class='bar'><h2>{esc(a.ticker)} | {esc(a.name)}</h2>"
           f"<div class='sub'>{sub}</div></div>"]
    if a.error:
        out.append(f"<div class='warn'>Not scored: {esc(a.error)}</div></div>")
        return "".join(out)
    if a.status != "PASS":
        out.append("<div class='amber'><b>DRAFT.</b> Not final under the publication gate (section 8.7): "
                   + esc("; ".join(a.draft_reasons) or "certification incomplete") + "</div>")
    out.append("<h3>Scorecard</h3>" + _scorecard(a))
    if a.risks:
        out.append("<div class='warn'>" + "<br>".join(esc(r) for r in a.risks) + "</div>")
    if a.sector_note:
        out.append(f"<div class='amber'>{esc(a.sector_note)}</div>")
    out.append("<h3>Quality Trend (separate from the score)</h3><p>" + f"<b>{esc(a.trend)}</b><br>"
               + "<br>".join(esc(n) for n in a.trend_notes) + "</p>")
    out.append("<h3>Audit trail: raw evidence, calculation, base score, overlay, final</h3>" + _audit_trail(a))
    out.append("<h3>Demonstrated Market Position: evidence register</h3>" + _register(a))
    ch = [(a.criteria[k].name, a.criteria[k].challenge) for k in ORDER if a.criteria[k].challenge]
    if ch:
        out.append("<h3>+/-0.5 score challenge</h3><table><tr><th>Criterion</th><th>Strongest case the score is wrong by 0.5, and band test</th></tr>"
                   + "".join(f"<tr><td>{esc(n)}</td><td class='small'>{esc(t)}</td></tr>" for n, t in ch) + "</table>")
    if a.exceptional_items:
        out.append("<h3>Statutory items the company called one-off (for review, not applied)</h3><table><tr><th>FY</th><th>Item</th><th>Source</th></tr>"
                   + "".join(f"<tr><td>{esc(str(x.get('fy', '')))}</td><td class='small'>{esc(str(x.get('description', '')))}</td>"
                             f"<td class='small'>{esc(str(x.get('source', '')))}</td></tr>" for x in a.exceptional_items) + "</table>")
    out.append("<h3>Calculation workpaper (EODHD statutory, reporting currency)</h3>" + _workpaper(a))
    out.append(f"<p class='note'>WACC used for Returns on Capital: {pct(a.wacc, 1)} (config/mike.yaml). "
               "NOPAT = EBIT x (1 - effective tax rate, bounded 0-35%). Invested capital = equity + gross debt including "
               "lease liabilities - cash and short-term investments.</p>")
    out.append("<h3>QA/QC certification (section 8.7)</h3>" + _certification(a))
    out.append("</div>")
    return "".join(out)


def build_pdf_html(assessments: list[Assessment], title: str, when: dt.datetime) -> str:
    n_pass = sum(a.status == "PASS" for a in assessments)
    cover = (f"<div class='cover'><h1>Mike | Stock Quality Assessment</h1>"
             f"<p><b style='color:#FFFFFF'>{esc(title)}</b></p>"
             f"<p>Framework: Stock Quality Assessment Framework v3.1, True 0-5 Demonstrated Track Record Rubric (Mikebrisy)</p>"
             f"<p>Assessment date {when:%d %B %Y} | {len(assessments)} companies | {n_pass} PASS, "
             f"{len(assessments) - n_pass} DRAFT or not scored</p></div>")
    method = ("<h3>How to read this report</h3><p class='small'>Each criterion is scored 0-5 in 0.5 steps from demonstrated, "
              "historical evidence only: forecasts, guidance, pipeline and TAM never raise a score. Quantitative base scores come "
              "straight from the framework's tables; qualitative overlays are limited to the permitted list and capped at +/-0.5. "
              "The overall score is the unweighted mean of the six criteria. Quality Trend is reported separately and never changes "
              "the score. A criterion at or below 1 is a material quality risk; 0 is an extreme one. An assessment is PASS only when "
              "every QA/QC control in section 8.7 passes; otherwise it is labelled DRAFT with the reasons. Figures are EODHD statutory "
              "statements: EODHD carries no underlying (management-adjusted) earnings, so statutory one-offs stay in the numbers and "
              "are listed for review.</p>")
    body = cover + "<h3>Summary</h3>" + _summary_table(assessments) + method + "".join(company_html(a) for a in assessments)
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"


def render_pdf(html_text: str, path: Path) -> None:
    from weasyprint import HTML  # lazy: only the workflow installs it
    HTML(string=html_text).write_pdf(str(path))


def inspect_pdf(path: Path, assessments: list[Assessment]) -> dict[str, tuple[bool, str]]:
    """The VISUAL/DOCUMENT control: open the rendered PDF and check, per
    company, that its section and scorecard are actually on the pages."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as exc:  # noqa: BLE001
        return {a.ticker: (False, f"could not open the rendered PDF ({exc.__class__.__name__})") for a in assessments}
    text = "\n".join(pages)
    blank = [i + 1 for i, t in enumerate(pages) if len(t.strip()) < 20]
    out = {}
    for a in assessments:
        hits = [i for i, t in enumerate(pages) if f"{a.ticker} | " in t]
        ok = bool(hits) and ("OVERALL QUALITY SCORE" in text or a.error) and not blank
        note = ("company section and scorecard found in the rendered PDF" if hits else "section not found in the PDF")
        if blank:
            note += f"; blank page(s) {blank}"
        out[a.ticker] = (bool(ok), note)
    return out


# ---------------------------------------------------------------------------
# Email (Bob's card style, table-only, inline styles)
# ---------------------------------------------------------------------------

def _badge(text: str, bg: str) -> str:
    return (f'<span style="display:inline-block; background:{bg}; color:#FFFFFF; font-size:10px; font-weight:800;'
            f' letter-spacing:0.6px; padding:3px 7px; border-radius:4px;">{esc(text)}</span>')


def _card(a: Assessment) -> str:
    head = (f'<tr><td colspan="2" style="background:{GREEN}; padding:13px 14px; font-family:{FONT};">'
            f'{_badge(a.classification.upper(), CLASS_COLOUR.get(a.classification, MUTED))}&nbsp;'
            f'{_badge(a.status, STATUS_COLOUR.get(a.status, MUTED))}'
            f'<div style="color:#FFFFFF; font-size:17px; font-weight:800; margin-top:7px;">{esc(a.ticker)} | {esc(a.name)}</div>'
            f'<div style="color:{GREEN_SUB}; font-size:12px; margin-top:3px;">Latest FY {esc(a.latest_fy)} | statements in {esc(a.currency or "n/a")}</div>'
            f'</td></tr>')
    if a.error:
        return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="360" style="width:100%; max-width:360px;'
                f' border-collapse:collapse; background:#FFFFFF; border-radius:10px; overflow:hidden; margin:0 auto 14px;">{head}'
                f'<tr><td colspan="2" style="padding:12px 14px; color:{RED}; font-family:{FONT}; font-size:14px;">Not scored: {esc(a.error)}</td></tr></table>')
    rows = ""
    for i, k in enumerate(ORDER):
        c = a.criteria[k]
        bg = SHADE if i % 2 == 0 else "#FFFFFF"
        col = RED if (c.final is not None and c.final <= 1) else VALUE
        rows += (f'<tr><td style="background:{bg}; padding:9px 14px; font-family:{FONT}; font-size:14px; color:{LABEL};">'
                 f'{esc(c.name)}<div style="font-size:11px; color:{MUTED}; margin-top:2px;">{esc(c.rationale)}</div></td>'
                 f'<td align="right" style="background:{bg}; padding:9px 14px; font-family:{FONT}; font-size:15px; font-weight:700;'
                 f' color:{col}; white-space:nowrap; vertical-align:top;">{s(c.final)}</td></tr>')
    rows += (f'<tr><td style="padding:11px 14px; font-family:{FONT}; font-size:15px; font-weight:800; color:{VALUE};'
             f' border-top:2px solid {GREEN};">Overall quality</td>'
             f'<td align="right" style="padding:11px 14px; font-family:{FONT}; font-size:17px; font-weight:800; color:{VALUE};'
             f' border-top:2px solid {GREEN}; white-space:nowrap;">{esc(overall_text(a))}</td></tr>')
    rows += (f'<tr><td colspan="2" style="padding:0 14px 11px; font-family:{FONT}; font-size:13px; color:{LABEL};">'
             f'Quality Trend: <b style="color:{TREND_COLOUR.get(a.trend, MUTED)}">{esc(a.trend)}</b>'
             f'<span style="color:{MUTED};"> (separate from the score)</span></td></tr>')
    if a.risks:
        rows += (f'<tr><td colspan="2" style="padding:10px 14px; background:#FEE2E2; color:{RED}; font-family:{FONT};'
                 f' font-size:13px; line-height:1.4;">' + "<br>".join(esc(r) for r in a.risks) + '</td></tr>')
    if a.status != "PASS":
        rows += (f'<tr><td colspan="2" style="padding:10px 14px; background:#FFFBEB; color:{AMBER}; font-family:{FONT};'
                 f' font-size:12px; line-height:1.4;"><b>DRAFT:</b> ' + esc("; ".join(a.draft_reasons)[:400]) + '</td></tr>')
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="360" style="width:100%; max-width:360px;'
            f' border-collapse:collapse; background:#FFFFFF; border-radius:10px; overflow:hidden; margin:0 auto 14px;">{head}{rows}</table>')


def email_html(assessments: list[Assessment], title: str, when: dt.datetime, pdf_ok: bool) -> str:
    ranked = sorted(assessments, key=lambda a: -(a.overall if a.overall is not None else -1))
    n_pass = sum(a.status == "PASS" for a in assessments)
    summary_rows = ""
    for i, a in enumerate(ranked):
        bg = SHADE if i % 2 == 0 else "#FFFFFF"
        summary_rows += (
            f'<tr><td style="background:{bg}; padding:8px 10px; font-family:{FONT}; font-size:14px; font-weight:700; color:{VALUE};">{esc(a.ticker)}</td>'
            f'<td align="right" style="background:{bg}; padding:8px 10px; font-family:{FONT}; font-size:14px; font-weight:700; color:{VALUE};">{esc(overall_text(a).replace(" (provisional)", "*"))}</td>'
            f'<td style="background:{bg}; padding:8px 10px; font-family:{FONT}; font-size:12px; font-weight:700; color:{CLASS_COLOUR.get(a.classification, MUTED)};">{esc(a.classification)}</td>'
            f'<td style="background:{bg}; padding:8px 10px; font-family:{FONT}; font-size:12px; color:{TREND_COLOUR.get(a.trend, MUTED)};">{esc(a.trend)}</td>'
            f'<td style="background:{bg}; padding:8px 10px; font-family:{FONT}; font-size:11px; font-weight:700; color:{STATUS_COLOUR.get(a.status, MUTED)};">{esc(a.status)}</td></tr>')
    summary = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="360" style="width:100%; max-width:360px;'
               f' border-collapse:collapse; background:#FFFFFF; border-radius:10px; overflow:hidden; margin:0 auto 14px;">'
               f'<tr><td colspan="5" style="background:{GREEN}; padding:13px 14px; font-family:{FONT};">'
               f'{_badge("QUALITY SCORECARD", "#F59E0B")}'
               f'<div style="color:#FFFFFF; font-size:17px; font-weight:800; margin-top:7px;">{esc(title)}</div>'
               f'<div style="color:{GREEN_SUB}; font-size:12px; margin-top:3px;">{len(assessments)} companies | {n_pass} PASS | framework v3.1</div>'
               f'</td></tr>{summary_rows}'
               f'<tr><td colspan="5" style="padding:10px 14px; font-family:{FONT}; font-size:12px; color:{MUTED}; background:{SHADE};">'
               + ("&#128206; Full assessment PDF attached: scorecards, audit trail, evidence registers and QA/QC certification."
                  if pdf_ok else f'<b style="color:{RED}">PDF failed to render; every assessment stays DRAFT.</b>')
               + ('<br>* provisional: fewer than six criteria scored.' if any(a.provisional for a in assessments) else '')
               + '</td></tr></table>')
    cards = "".join(_card(a) for a in ranked)
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background:{NAVY}; border-collapse:collapse;">'
            f'<tr><td align="center" style="padding:16px 10px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="380" style="width:100%; max-width:380px; border-collapse:collapse;">'
            f'<tr><td style="padding:4px 4px 14px; font-family:{FONT}; color:#E5E7EB;">'
            f'<div style="font-size:20px; font-weight:800; color:#FFFFFF;">Mike | Stock Quality</div>'
            f'<div style="font-size:12px; color:#9CA3AF; margin-top:3px;">{when:%a %d %b %Y} | demonstrated track record only, no forecasts</div>'
            f'</td></tr><tr><td>{summary}{cards}</td></tr>'
            f'<tr><td style="padding:8px 4px; font-family:{FONT}; font-size:11px; color:#9CA3AF;">'
            f'Mikebrisy\'s Stock Quality Assessment Framework v3.1, scored by Mike from EODHD statutory statements. '
            f'Market Position evidence is gathered by a model with web search and checked in code; every point needs a source.'
            f'</td></tr></table></td></tr></table>')


def email_text(assessments: list[Assessment], title: str) -> str:
    lines = [f"Mike | Stock Quality: {title}", ""]
    for a in sorted(assessments, key=lambda a: -(a.overall if a.overall is not None else -1)):
        if a.error:
            lines.append(f"{a.ticker}: not scored ({a.error})")
            continue
        lines.append(f"{a.ticker} {overall_text(a)} {a.classification} | trend {a.trend} | {a.status}")
        lines.append("   " + " | ".join(f"{SHORT[k]} {s(a.criteria[k].final)}" for k in ORDER))
    lines += ["", "Full assessment PDF attached."]
    return "\n".join(lines)
