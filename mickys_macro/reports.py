"""Email builders for Micky's Macro's five outputs (brief section 12).

Table-based HTML with inline styles only, same hard rule every other
agent's email follows (Gmail/Outlook strip ``<style>`` blocks and mishandle
flex/grid -- see CLAUDE.md's "Email HTML constraints" note on Bob). No
``<style>``, no ``class=``, no ``display:flex``/``display:grid``.

Visual language follows Slinger/Shorty, not a flat dark-on-dark card: a
dark outer panel, white rounded cards with a coloured header bar per item,
and section bars that colour-code what kind of content follows. The email
is a glance -- one short paragraph and a few headline numbers per item,
same "email is the glance, the PDF is the analysis" split every other
agent in this repo uses (Bob's native Doc, Slinger's/Harry's attached
PDF). The full dossier/candidate/scorecard detail renders into a
standalone PDF by ``pdf_render.py``, built from the same *Inputs
dataclasses defined here so there is one source of truth for the content,
not two.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass

from .schemas import CompanyCandidate, EmailRecord, ExtractedClaim, TrendDossier, TrendScore

# ---------------------------------------------------------------------------
# Palette -- dark panel shell, white cards with a coloured header bar.
# Mirrors sgx_email.py / shorty_email.py so every agent's email reads as
# one family; Micky's Macro's own accent is royal blue (#1D4ED8) rather
# than Harry's indigo or Slinger's green.
# ---------------------------------------------------------------------------

_BG = "#0b1220"
_PANEL = "#111b2e"
_TEXT_ON_DARK = "#e2e8f0"
_MUTED_ON_DARK = "#94a3b8"
_ACCENT = "#1d4ed8"
_ACCENT_SUB = "#bfdbfe"

_CARD_BG = "#ffffff"
_LABEL = "#374151"
_VALUE = "#111827"
_MUTED_ON_LIGHT = "#6b7280"
_ROW_SHADE = "#f1f5f9"
_LINK = "#2563eb"

_SECTION_COLOURS = {
    "theses": "#f59e0b",       # amber -- new or changed macro theses
    "opportunities": "#3b82f6",  # blue -- new investable opportunities
    "contradicting": "#ef4444",  # red -- evidence against an existing thesis
    "portfolio": "#10b981",     # green -- portfolio/watchlist implications
    "indicators": "#64748b",    # slate -- what to watch next
}

_EXPOSURE_HEADER = {
    "DIRECT_BENEFICIARY": ("#065f46", "#a7f3d0"),
    "BOTTLENECK_SUPPLIER": ("#1e3a8a", "#bfdbfe"),
    "ENABLER": ("#5b21b6", "#ddd6fe"),
    "POTENTIAL_LOSER": ("#991b1b", "#fecaca"),
}

MICKYS_MACRO_NAME = "Micky's Macro"
TAGLINE = "What does the world increasingly need, and who gets paid for supplying it?"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif"


def _esc(v: object) -> str:
    return _html.escape(str(v if v is not None else ""), quote=True)


def _trunc(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _td(label: str, value: str, *, shade: bool = False) -> str:
    bg = f"background:{_ROW_SHADE};" if shade else ""
    return (
        f"<tr><td style='{bg}color:{_LABEL};font-size:11px;padding:5px 8px;font-weight:600'>{_esc(label)}</td>"
        f"<td style='{bg}color:{_VALUE};font-size:12px;padding:5px 8px;text-align:right;font-weight:700'>{_esc(value)}</td></tr>"
    )


def _list_html(items: list[str], limit: int = 5, *, on_dark: bool = True) -> str:
    colour = _TEXT_ON_DARK if on_dark else _VALUE
    if not items:
        return f"<div style='color:{_MUTED_ON_DARK if on_dark else _MUTED_ON_LIGHT};font-size:12px'>none yet</div>"
    rows = "".join(f"<li style='margin:3px 0;line-height:1.4'>{_esc(i)}</li>" for i in items[:limit])
    more = len(items) - limit
    tail = f"<li style='margin:3px 0;color:{_MUTED_ON_DARK if on_dark else _MUTED_ON_LIGHT}'>+{more} more in the attached PDF</li>" if more > 0 else ""
    return f"<ul style='margin:4px 0 0 16px;padding:0;color:{colour};font-size:12px'>{rows}{tail}</ul>"


def _section_bar(title: str, colour: str) -> str:
    return (
        f"<table role='presentation' style='width:100%;border-collapse:collapse;margin:18px 0 8px'><tr><td "
        f"style='padding:9px 12px;background:{colour};color:#0b1220;font-weight:800;font-size:12px;"
        f"letter-spacing:0.5px;border-radius:8px'>{_esc(title.upper())}</td></tr></table>"
    )


def _card(header_title: str, header_sub: str, body_html: str, *, header_bg: str = _ACCENT, header_sub_colour: str = _ACCENT_SUB) -> str:
    """One white rounded card with a coloured header bar -- the Slinger/
    Shorty look, not a flat dark-on-dark card."""
    return (
        f"<table role='presentation' style='width:100%;border-collapse:collapse;background:{_CARD_BG};"
        f"border-radius:10px;overflow:hidden;margin:10px 0;box-shadow:0 1px 3px rgba(0,0,0,0.25)'>"
        f"<tr><td style='padding:10px 14px;background:{header_bg};color:#ffffff;font-weight:700;font-size:13px'>"
        f"{_esc(header_title)}"
        f"<span style='display:block;font-weight:400;font-size:11px;color:{header_sub_colour};margin-top:2px'>{_esc(header_sub)}</span>"
        f"</td></tr>"
        f"<tr><td style='padding:12px 14px;color:{_VALUE};font-size:12px;line-height:1.5'>{body_html}</td></tr>"
        f"</table>"
    )


def _header_html(title: str, subtitle: str, note: str = "") -> str:
    return (
        f"<table role='presentation' style='width:100%;border-collapse:collapse;background:{_BG};padding:0'>"
        f"<tr><td style='padding:20px 18px 6px'>"
        f"<div style='font-size:22px;font-weight:900;color:#ffffff'>{_esc(MICKYS_MACRO_NAME)}</div>"
        f"<div style='font-size:12px;color:{_MUTED_ON_DARK};margin-top:2px;font-style:italic'>{_esc(TAGLINE)}</div>"
        f"<div style='font-size:14px;color:{_TEXT_ON_DARK};margin-top:10px;font-weight:600'>{_esc(title)}</div>"
        f"<div style='font-size:12px;color:{_MUTED_ON_DARK};margin-top:2px'>{_esc(subtitle)}</div>"
        + (f"<div style='font-size:11px;color:{_MUTED_ON_DARK};margin-top:8px;font-style:italic'>{_esc(note)}</div>" if note else "")
        + "</td></tr></table>"
    )


def _footer_html() -> str:
    return (
        f"<table role='presentation' style='width:100%;border-collapse:collapse'><tr><td "
        f"style='padding:16px 18px;color:{_MUTED_ON_DARK};font-size:10px;border-top:1px solid #1e293b;margin-top:10px'>"
        f"Research and decision support only -- Micky's Macro never buys, sells or resizes anything. "
        f"A macro trend being real does not make every company tagged to it a good investment at today's price."
        f"</td></tr></table>"
    )


def _shell(header: str, sections_html: str) -> str:
    return (
        f"<table role='presentation' style='width:100%;max-width:660px;border-collapse:collapse;background:{_BG}'>"
        f"<tr><td>{header}"
        f"<table role='presentation' style='width:100%;border-collapse:collapse'><tr><td style='padding:0 18px 18px'>"
        f"{sections_html}</td></tr></table>"
        f"{_footer_html()}</td></tr></table>"
    )


def _pdf_note(label: str = "attached PDF") -> str:
    return f"<div style='margin-top:8px;font-size:11px;color:{_MUTED_ON_LIGHT};font-style:italic'>Full detail in the {label}.</div>"


# ---------------------------------------------------------------------------
# A. Daily Macro Brief
# ---------------------------------------------------------------------------

@dataclass
class DailyBriefInputs:
    run_date: str
    new_claims: list[ExtractedClaim]
    updated_dossiers: list[TrendDossier]
    new_candidates: list[CompanyCandidate]
    contradicting_evidence: list[str]
    portfolio_notes: list[str]
    next_indicators: list[str]
    emails_processed: int
    emails_skipped_duplicate: int


def _dossier_glance_card(d: TrendDossier) -> str:
    body = (
        f"<div>{_esc(_trunc(d.thesis or d.what_changing_and_why, 320))}</div>"
        + (f"<div style='margin-top:6px;color:{_MUTED_ON_LIGHT};font-size:11px'>Winners named so far: "
           f"{_esc(', '.join(d.winners[:4]) or 'none yet')}</div>" if d.winners else "")
        + _pdf_note()
    )
    sub = f"{d.category.replace('_', ' ').title()} · {d.secular_or_cyclical.replace('_', ' ').title()} · confidence {d.confidence.lower()}"
    return _card(d.name, sub, body)


def _candidate_glance_card(c: CompanyCandidate) -> str:
    header_bg, header_sub_colour = _EXPOSURE_HEADER.get(c.exposure_type, (_ACCENT, _ACCENT_SUB))
    v = c.valuation
    stat = ""
    if v.pe is not None:
        stat = f"P/E {v.pe:.1f}x"
    elif v.not_covered_reason:
        stat = "valuation: not covered"
    body = (
        f"<div>{_esc(_trunc(c.why_now, 280))}</div>"
        + (f"<div style='margin-top:6px;color:{_MUTED_ON_LIGHT};font-size:11px'>{_esc(stat)}</div>" if stat else "")
        + (f"<div style='margin-top:4px;color:{_MUTED_ON_LIGHT};font-size:11px'>Portfolio: {_esc(', '.join(c.portfolio_overlap))}</div>"
           if c.portfolio_overlap else "")
        + _pdf_note()
    )
    header = f"{c.ticker} ({c.exchange or 'n/a'})" + (f" — {c.name}" if c.name else "")
    sub = c.exposure_type.replace("_", " ").title()
    return _card(header, sub, body, header_bg=header_bg, header_sub_colour=header_sub_colour)


def build_daily_brief(inp: DailyBriefInputs) -> tuple[str, str, str]:
    subject = f"Micky's Macro | Daily Brief | {inp.run_date}"
    subtitle = f"{inp.emails_processed} new research email(s) · {inp.emails_skipped_duplicate} already seen"

    if not inp.updated_dossiers and not inp.new_candidates and not inp.contradicting_evidence:
        text = (
            f"Micky's Macro Daily Brief -- {inp.run_date}\n\n"
            f"Nothing material changed. {inp.emails_processed} new email(s) processed, "
            f"{inp.emails_skipped_duplicate} already seen.\n"
        )
        header = _header_html(f"Daily Brief · {inp.run_date}", subtitle)
        body = (
            f"<div style='padding:14px;background:{_PANEL};border-radius:10px;color:{_TEXT_ON_DARK};font-size:13px'>"
            "No material change today.</div>"
        )
        return subject, text, _shell(header, body)

    sections_html = ""
    text_lines = [f"Micky's Macro Daily Brief -- {inp.run_date}", ""]

    if inp.updated_dossiers:
        sections_html += _section_bar("New or changed macro theses", _SECTION_COLOURS["theses"])
        sections_html += "".join(_dossier_glance_card(d) for d in inp.updated_dossiers[:5])
        text_lines.append(f"THESES UPDATED: {', '.join(d.name for d in inp.updated_dossiers)}")

    if inp.new_candidates:
        sections_html += _section_bar("New investable opportunities", _SECTION_COLOURS["opportunities"])
        sections_html += "".join(_candidate_glance_card(c) for c in inp.new_candidates[:5])
        text_lines.append(f"NEW CANDIDATES: {', '.join(c.ticker for c in inp.new_candidates)}")

    if inp.contradicting_evidence:
        sections_html += _section_bar("Evidence against an existing thesis", _SECTION_COLOURS["contradicting"])
        sections_html += _card("Contradicting evidence", "worth a second look", _list_html(inp.contradicting_evidence, on_dark=False), header_bg="#991b1b", header_sub_colour="#fecaca")

    if inp.portfolio_notes:
        sections_html += _section_bar("Portfolio & watchlist implications", _SECTION_COLOURS["portfolio"])
        sections_html += _card("Overlap with what you already hold or watch", "", _list_html(inp.portfolio_notes, on_dark=False), header_bg="#065f46", header_sub_colour="#a7f3d0")

    if inp.next_indicators:
        sections_html += _section_bar("Next indicators to watch", _SECTION_COLOURS["indicators"])
        sections_html += _card("Leading indicators", "", _list_html(inp.next_indicators, on_dark=False), header_bg="#334155", header_sub_colour="#cbd5e1")

    header = _header_html(f"Daily Brief · {inp.run_date}", subtitle, "Full dossier and candidate detail is in the attached PDF.")
    text_lines.append("")
    text_lines.append("Full detail in the attached PDF.")
    return subject, "\n".join(text_lines), _shell(header, sections_html)


# ---------------------------------------------------------------------------
# B. Weekly Macro Investment Review
# ---------------------------------------------------------------------------

@dataclass
class WeeklyReviewInputs:
    week_ending: str
    ranked: list[tuple[TrendDossier, TrendScore | None]]
    conviction_changes: list[str]
    new_bottlenecks: list[str]
    improving_companies: list[str]
    deteriorating_companies: list[str]
    valuation_concerns: list[str]
    portfolio_cross_check: list[str]
    next_to_investigate: list[str]
    strongest_counterarguments: list[str]


_SCORE_DIMENSION_LABELS = (
    ("structural_demand_strength", "Demand"),
    ("expected_duration", "Duration"),
    ("supply_scarcity", "Supply scarcity"),
    ("evidence_quality", "Evidence quality"),
    ("monetisation_visibility", "Monetisation"),
    ("industry_economics", "Industry economics"),
    ("investable_company_availability", "Investable companies"),
    ("valuation_attractiveness", "Valuation"),
    ("portfolio_diversification", "Diversification"),
    ("consensus_crowding_risk", "Consensus/crowding"),
)


def _score_glance_row(score: TrendScore | None) -> str:
    if score is None:
        return f"<div style='color:{_MUTED_ON_LIGHT};font-size:11px'>not yet scored</div>"
    cells = "".join(
        f"<td style='padding:4px 6px;text-align:center'>"
        f"<div style='font-size:14px;font-weight:800;color:{_VALUE}'>{getattr(score, key).score}</div>"
        f"<div style='font-size:9px;color:{_MUTED_ON_LIGHT}'>{label}</div></td>"
        for key, label in _SCORE_DIMENSION_LABELS
    )
    return f"<table style='width:100%;border-collapse:collapse;margin-top:6px'><tr>{cells}</tr></table>"


def _ranked_dossier_card(rank: int, d: TrendDossier, score: TrendScore | None) -> str:
    body = f"<div>{_esc(_trunc(d.thesis, 260))}</div>{_score_glance_row(score)}{_pdf_note()}"
    sub = f"{d.category.replace('_', ' ').title()} · {d.secular_or_cyclical.replace('_', ' ').title()}"
    return _card(f"#{rank} · {d.name}", sub, body)


def build_weekly_review(inp: WeeklyReviewInputs) -> tuple[str, str, str]:
    subject = f"Micky's Macro | Weekly Investment Review | week ending {inp.week_ending}"
    header = _header_html(
        f"Weekly Investment Review · week ending {inp.week_ending}",
        "Ranking is for readability only -- the ten scores are never averaged into one number.",
        "Attractive trend, industry, company and investment at today's price are four different conclusions.",
    )

    sections_html = _section_bar("Ranked structural trends", _ACCENT)
    sections_html += "".join(_ranked_dossier_card(i + 1, d, s) for i, (d, s) in enumerate(inp.ranked[:10]))

    extra_sections = [
        ("Changes in conviction and why", inp.conviction_changes, "#f59e0b"),
        ("New bottlenecks / emerging opportunities", inp.new_bottlenecks, "#3b82f6"),
        ("Companies with improving investment cases", inp.improving_companies, "#10b981"),
        ("Companies with deteriorating investment cases", inp.deteriorating_companies, "#ef4444"),
        ("Valuation and consensus concerns", inp.valuation_concerns, "#f59e0b"),
        ("Cross-checks against the existing portfolio", inp.portfolio_cross_check, "#10b981"),
        ("Most interesting opportunities to investigate next", inp.next_to_investigate, "#3b82f6"),
        ("Strongest counterarguments", inp.strongest_counterarguments, "#ef4444"),
    ]
    for title, items, colour in extra_sections:
        if not items:
            continue
        sections_html += _section_bar(title, colour)
        sections_html += _card(title, "", _list_html(items, on_dark=False), header_bg=colour, header_sub_colour="#ffffff")

    text = f"Micky's Macro Weekly Investment Review -- week ending {inp.week_ending}\n\nFull detail in the attached PDF.\n"
    return subject, text, _shell(header, sections_html)


# ---------------------------------------------------------------------------
# D. Company Opportunity Brief
# ---------------------------------------------------------------------------

def build_company_opportunity_brief(candidate: CompanyCandidate, dossier: TrendDossier) -> tuple[str, str, str]:
    subject = f"Micky's Macro | Company Opportunity Brief | {candidate.ticker}"
    header_bg, header_sub_colour = _EXPOSURE_HEADER.get(candidate.exposure_type, (_ACCENT, _ACCENT_SUB))
    v = candidate.valuation
    val_rows = "".join(
        [
            _td("Price", f"{v.price} {v.currency}" if v.price is not None else "n/a", shade=True),
            _td("P/E (trailing)", f"{v.pe:.1f}x" if v.pe is not None else "n/a"),
            _td("Forward P/E", f"{v.forward_pe:.1f}x" if v.forward_pe is not None else "n/a", shade=True),
            _td("EV/EBITDA", f"{v.ev_ebitda:.1f}x" if v.ev_ebitda is not None else "n/a"),
            _td("Dividend yield", f"{v.dividend_yield_pct:.1f}%" if v.dividend_yield_pct is not None else "n/a", shade=True),
            _td("FCF yield", f"{v.fcf_yield_pct:.1f}%" if v.fcf_yield_pct is not None else "n/a"),
        ]
    )
    if v.not_covered_reason:
        val_rows += _td("Coverage", v.not_covered_reason, shade=True)
    filt = candidate.investment_filter
    body = (
        f"<div><b>Why the opportunity exists.</b> {_esc(_trunc(dossier.thesis, 320))}</div>"
        f"<div style='margin-top:6px'><b>Why now.</b> {_esc(_trunc(candidate.why_now, 240))}</div>"
        f"<table style='width:100%;border-collapse:collapse;margin-top:10px'>{val_rows}</table>"
        f"<div style='margin-top:10px'><b>Valuation read.</b> {_esc(_trunc(filt.valuation_and_prospective_return, 260))}</div>"
        f"<div style='margin-top:6px;color:{_MUTED_ON_LIGHT};font-size:11px'>Portfolio overlap: "
        f"{_esc(', '.join(candidate.portfolio_overlap) or 'none found')}</div>"
        + _pdf_note()
    )
    header = f"{candidate.ticker} ({candidate.exchange or 'n/a'})" + (f" — {candidate.name}" if candidate.name else "")
    header_html = _header_html(f"Company Opportunity Brief · {candidate.ticker}", dossier.name,
                                "Full causal chain, risks and investment filter in the attached PDF.")
    sections_html = _card(header, candidate.exposure_type.replace("_", " ").title(), body,
                          header_bg=header_bg, header_sub_colour=header_sub_colour)
    text = f"Micky's Macro Company Opportunity Brief -- {candidate.ticker}\n\nFull detail in the attached PDF.\n"
    return subject, text, _shell(header_html, sections_html)


# ---------------------------------------------------------------------------
# E. Gmail Research Digest
# ---------------------------------------------------------------------------

def build_gmail_digest(emails: list[EmailRecord], claims_by_email: dict[str, list[ExtractedClaim]]) -> tuple[str, str, str]:
    subject = f"Micky's Macro | Gmail Research Digest | {len(emails)} new item(s)"
    header = _header_html("Gmail Research Digest", f"{len(emails)} new item(s) from the four priority sources")
    if not emails:
        body = f"<div style='padding:14px;background:{_PANEL};border-radius:10px;color:{_TEXT_ON_DARK};font-size:13px'>No new research emails.</div>"
        return subject, "No new research emails.\n", _shell(header, body)

    sections_html = ""
    for e in emails:
        claims = claims_by_email.get(e.id, [])
        claim_lines = [f"[{c.claim_type}] {_trunc(c.text, 160)}" for c in claims]
        link_html = (
            f"<div style='margin-top:8px'><a href='{_esc(e.gmail_link)}' style='color:{_LINK};font-size:11px'>Open in Gmail</a></div>"
            if e.gmail_link else ""
        )
        body = _list_html(claim_lines, limit=5, on_dark=False) + link_html
        sections_html += _card(e.subject or "(no subject)", f"{e.source_name} · {e.received_at[:10]}", body)

    text_lines = [f"Micky's Macro Gmail Research Digest -- {len(emails)} new item(s)", ""]
    for e in emails:
        text_lines.append(f"- {e.source_name}: {e.subject}")
    return subject, "\n".join(text_lines), _shell(header, sections_html)
