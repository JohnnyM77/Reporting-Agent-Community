"""Esther's email and markdown.

Email HTML follows the repo rule for every agent email: tables and inline
styles only, no <style>, no class=, no flex/grid (Outlook and Gmail mobile
mangle anything else). The Simply Wall St inputs sit at the top of each
company so JM never has to hunt for them (spec s.8).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Optional

from esther.context import Portfolio
from esther.quality import QCResult
from esther.valuation import ValuationResult

MODES = ("full", "quick", "valuation", "thesis", "challenge")

INK, MUTED, RULE, PAPER = "#1b1b1b", "#6b6b6b", "#e2ddd3", "#ffffff"
ACCENT = "#7a2e8e"  # Esther purple, so her card is recognisable next to Bob's and Harry's
GOOD, BAD, WARN = "#1f7a3a", "#b3261e", "#9a6700"
FONT = "font-family:Georgia,'Times New Roman',serif;"
SANS = "font-family:Arial,Helvetica,sans-serif;"
MONO = "font-family:Consolas,'Courier New',monospace;"

CCY_SYMBOL = {"AUD": "A$", "USD": "US$", "GBP": "£", "GBp": "p", "SGD": "S$", "NZD": "NZ$", "EUR": "€"}


@dataclass
class Report:
    ticker: str
    company: str
    status: str  # OK / FAILED_API / FAILED_INVALID / SKIPPED_CAP
    portfolio: Portfolio
    analysis: dict = field(default_factory=dict)
    valuation: Optional[ValuationResult] = None
    valuation_error: str = ""
    qc: Optional[QCResult] = None
    error: str = ""
    figure_sources: list[str] = field(default_factory=list)

    @property
    def price_ccy(self) -> str:
        return self.valuation.base.price_currency if self.valuation else "AUD"


def money(v: Optional[float], ccy: str = "AUD") -> str:
    if v is None:
        return "n/a"
    return f"{CCY_SYMBOL.get(ccy, ccy + ' ')}{v:,.2f}"


def pct(v: Optional[float], signed: bool = False, dp: int = 1) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:+.{dp}f}%" if signed else f"{v * 100:.{dp}f}%"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


# ---------------------------------------------------------------------------
# Plain blocks shared by email, text and markdown
# ---------------------------------------------------------------------------

def sws_inputs_text(r: Report) -> str:
    v = r.valuation
    if not v:
        return "SIMPLY WALL STREET INPUTS\nInsufficient evidence to make this assumption confidently.\n" + (
            f"({r.valuation_error})" if r.valuation_error else "")
    n, ccy = v.narrative, v.base.price_currency
    lines = ["SIMPLY WALL STREET INPUTS", "",
             f"Revenue growth: {pct(n.revenue_growth)}",
             f"Profit margin: {pct(n.net_margin)}",
             f"Future P/E: {n.future_pe:.1f}x",
             "",
             f"MY VALUE: {money(v.value, ccy)}",
             f"CURRENT PRICE: {money(v.price, ccy)}",
             f"UPSIDE/DOWNSIDE: {pct(v.upside, signed=True)}",
             ""]
    if v.dividends_pv:
        lines.append(f"(SWS ignores dividends. Today's dividend held flat for {v.base.years} years adds "
                     f"{money(v.dividends_pv, ccy)}: {money(v.value_with_dividends, ccy)}, "
                     f"{pct(v.upside_with_dividends, signed=True)})")
    lines.append(f"(SWS settings: {v.base.years} years, discount rate {pct(v.base.discount_rate, dp=2)}, "
                 f"shares {pct(v.base.share_change_pa, signed=True)} a year)")
    return "\n".join(lines)


def valuation_summary_text(r: Report) -> str:
    v = r.valuation
    if not v:
        return ""
    n, ccy = v.narrative, v.base.price_currency
    out = ["NARRATIVE CASE (published)",
           f"Revenue growth {pct(n.revenue_growth)}, net margin {pct(n.net_margin)}, future P/E {n.future_pe:.1f}x",
           f"Why: {n.rationale}",
           f"My value: {money(v.value, ccy)} vs price {money(v.price, ccy)} ({pct(v.upside, signed=True)})"]
    if v.dividends_pv:
        out.append(f"Plus dividends (not in SWS): {money(v.dividends_pv, ccy)} -> "
                   f"{money(v.value_with_dividends, ccy)} ({pct(v.upside_with_dividends, signed=True)})")
    if v.implied_growth_at_price is not None:
        out.append(f"Mr Market's implied growth: {pct(v.implied_growth_at_price)} a year gets you to today's price "
                   f"on the same margin and P/E.")
    if v.stress:
        st = v.stress
        out += ["", "STRESS TEST (private, not for publishing)",
                f"Revenue growth {pct(st.revenue_growth)}, net margin {pct(st.net_margin)}, future P/E {st.future_pe:.1f}x"
                f" -> {money(st.value_today, ccy)}",
                f"Why: {st.rationale}"]
    return "\n".join(out)


def narrative_with_disclosure(r: Report, quick: bool = False) -> tuple[str, str]:
    a = r.analysis
    if quick:
        q = a.get("quick_update") or {}
        title, body = q.get("title") or a.get("title", ""), q.get("narrative", "")
    else:
        title, body = a.get("title", ""), a.get("narrative", "")
    disc = r.portfolio.disclosure
    if disc and disc not in body:
        body = body.rstrip() + "\n\n" + disc
    return title, body


# ---------------------------------------------------------------------------
# Markdown (attached to the email, one file per company)
# ---------------------------------------------------------------------------

def to_markdown(r: Report, mode: str) -> str:
    a = r.analysis
    L = [f"# {r.ticker}: {r.company}", ""]
    if r.status != "OK" and not a:
        return "\n".join(L + [f"**{r.status}**: {r.error}"])
    L += [f"*Esther the Wrestler, mode {mode.upper()}. Event: {a.get('event', 'n/a')}*", "",
          f"**Portfolio:** {r.portfolio.status}  ", f"**Recommendation:** {a.get('publish_recommendation', 'n/a')}"
          f", {a.get('publish_reason', '')}", ""]
    if r.status != "OK":
        L += [f"> **{r.status}**: {r.error}", ""]
    L += ["```", sws_inputs_text(r), "```", ""]

    if mode in ("full", "quick"):
        title, body = narrative_with_disclosure(r, quick=(mode == "quick"))
        L += ["---", "## PUBLISH-READY COPY", "", f"### {title}", "", body, "", "---", ""]
        if mode == "quick":
            L += [f"**So what?** {a.get('so_what', '')}", ""]
    if mode in ("full", "thesis", "challenge"):
        tc = a.get("thesis_check") or {}
        L += [f"## Thesis check: {tc.get('verdict', 'n/a')}", tc.get("why", ""), "",
              f"**If I didn't already own it:** {a.get('would_i_own_it_fresh', '')}", ""]
    if mode in ("full", "thesis"):
        L += ["## What changed?", *_md_list(a.get("what_changed")), "",
              "## What did not change?", *_md_list(a.get("what_did_not_change")), "",
              "## What assumption needs to change?", *_md_list(a.get("assumptions_to_change")), ""]
    if mode in ("full",):
        L += ["## My read", a.get("my_read", ""), "", "## The numbers", "| | | |", "|---|---|---|"]
        L += [f"| {n.get('label', '')} | {n.get('value', '')} | {n.get('note', '')} |" for n in a.get("the_numbers") or []]
        L += ["", f"**Statutory vs underlying:** {a.get('statutory_vs_underlying', '')}", "",
              f"**Cash flow and balance sheet:** {a.get('cash_flow_and_balance_sheet', '')}", "",
              "## Management claims, tested"]
        L += [f"- **{c.get('verdict', '')}**: {c.get('claim', '')} ({c.get('evidence', '')})"
              for c in a.get("management_claims_tested") or []]
        L += [""]
    if mode in ("full", "valuation"):
        L += ["## Valuation summary", "```", valuation_summary_text(r), "```",
              f"**Key assumption doing the work:** {a.get('key_valuation_driver', '')}", "",
              f"**Biggest valuation risk:** {a.get('biggest_valuation_risk', '')}", ""]
        if r.valuation and r.valuation.warnings:
            L += ["**Consistency warnings:** " + "; ".join(r.valuation.warnings), ""]
    if mode in ("full", "challenge"):
        ch = a.get("challenge") or {}
        L += ["## Challenge my thesis",
              f"1. **Strongest argument against owning it:** {ch.get('strongest_argument_against', '')}",
              f"2. **Weakest assumption in the valuation:** {ch.get('weakest_assumption', '')}",
              f"3. **The number I'm most likely fooling myself with:** {ch.get('number_jm_is_fooling_himself_with', '')}",
              f"4. **What the market may understand that I don't:** {ch.get('what_the_market_may_understand', '')}",
              f"5. **Evidence that would force a sell/rethink:** {ch.get('evidence_that_forces_a_rethink', '')}", ""]
    if mode in ("full", "thesis", "challenge"):
        L += ["## What would change my mind?", *_md_list(a.get("what_would_change_my_mind")), "",
              "## What I'm watching next", *_md_list(a.get("watching_next")), ""]
    if mode == "full":
        L += ["## Evidence", "| Source | Date | Fact | Why it matters |", "|---|---|---|---|"]
        L += [f"| {e.get('source', '')} | {e.get('date', '')} | {e.get('fact', '')} | {e.get('why_it_matters', '')} |"
              for e in a.get("evidence") or []]
        if a.get("insufficient_evidence"):
            L += ["", "**Insufficient evidence:**", *_md_list(a.get("insufficient_evidence"))]
        if r.figure_sources:
            L += ["", "**Where the base figures came from:**", *_md_list(r.figure_sources)]
        if r.qc:
            L += ["", "## Quality control", *[f"- [{'x' if ok else ' '}] {item}{f' ({note})' if note else ''}"
                                              for item, ok, note in r.qc.checks]]
            if r.qc.model_self_check:
                L += ["", "*Esther's own self-check (model-reported, not verified):* " + ", ".join(
                    f"{k.replace('_', ' ')}: {'yes' if v else 'NO'}" for k, v in r.qc.model_self_check.items())]
    return "\n".join(str(x) for x in L).rstrip() + "\n"


def _md_list(items) -> list[str]:
    return [f"- {i}" for i in (items or [])] or ["- n/a"]


# ---------------------------------------------------------------------------
# Email HTML
# ---------------------------------------------------------------------------

def _td(content: str, style: str = "") -> str:
    return f'<td style="padding:6px 8px;border-bottom:1px solid {RULE};vertical-align:top;{style}">{content}</td>'


def _section(title: str, inner: str) -> str:
    return (f'<tr><td style="padding:14px 16px 4px 16px;{SANS}font-size:11px;letter-spacing:1px;'
            f'color:{ACCENT};font-weight:bold;">{esc(title.upper())}</td></tr>'
            f'<tr><td style="padding:0 16px 8px 16px;{FONT}font-size:15px;line-height:1.5;color:{INK};">{inner}</td></tr>')


def _list_html(items) -> str:
    items = items or []
    if not items:
        return f'<span style="color:{MUTED};">n/a</span>'
    return "".join(f'<div style="margin:0 0 4px 0;">&bull; {esc(i)}</div>' for i in items)


def _md_to_html(md: str) -> str:
    """Just enough markdown for a narrative: ## headings, paragraphs, **bold**."""
    out, para = [], []

    def flush() -> None:
        if para:
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", "<br>".join(esc(x) for x in para))
            out.append(f'<p style="margin:0 0 10px 0;">{text}</p>')
            para.clear()

    for line in (md or "").strip().splitlines():
        line = line.strip()
        if not line:
            flush()
        elif line.startswith("#"):
            flush()
            out.append(f'<div style="{SANS}font-weight:bold;font-size:14px;margin:12px 0 4px 0;">'
                       f'{esc(line.lstrip("#").strip())}</div>')
        else:
            para.append(line)
    flush()
    return "".join(out)


def _chip(text: str, colour: str) -> str:
    return (f'<span style="{SANS}font-size:11px;font-weight:bold;color:{colour};border:1px solid {colour};'
            f'padding:1px 6px;">{esc(text)}</span>')


def _sws_html(r: Report) -> str:
    v = r.valuation
    if not v:
        return (f'<div style="{SANS}color:{BAD};">Insufficient evidence to make this assumption confidently.'
                f' {esc(r.valuation_error)}</div>')
    n, ccy = v.narrative, v.base.price_currency
    rows = [("Revenue growth", pct(n.revenue_growth)), ("Profit margin", pct(n.net_margin)),
            ("Future P/E", f"{n.future_pe:.1f}x")]
    body = "".join("<tr>" + _td(esc(lbl), f"{SANS}font-size:13px;color:{MUTED};")
                   + _td(f"<b>{esc(x)}</b>", f"{MONO}font-size:16px;") + "</tr>" for lbl, x in rows)
    up = v.upside
    up_col = GOOD if (up or 0) > 0.05 else WARN if (up or 0) > -0.15 else BAD
    foot = (f'<tr><td colspan="2" style="padding:8px;{MONO}font-size:14px;background:#f6f1fa;">'
            f'MY VALUE: <b>{money(v.value, ccy)}</b> &nbsp; CURRENT PRICE: <b>{money(v.price, ccy)}</b>'
            f' &nbsp; UPSIDE/DOWNSIDE: <b style="color:{up_col};">{pct(up, signed=True)}</b></td></tr>')
    note = (f'<div style="{SANS}font-size:11px;color:{MUTED};margin-top:4px;">SWS settings: {v.base.years} years, '
            f'discount rate {pct(v.base.discount_rate, dp=2)}, shares {pct(v.base.share_change_pa, signed=True)} a year. '
            f'Revenue base {v.base.report_currency} {v.base.revenue_m:,.0f}m, {v.base.shares_m:,.0f}m shares'
            + (f', FX {v.base.report_currency}/{v.base.price_currency} {v.base.fx_report_to_price:.4f}'
               if v.base.report_currency != v.base.price_currency else "")
            + ". If SWS shows a different discount rate for this stock, use its rate: the value will move.</div>")
    if v.dividends_pv:
        note += (f'<div style="{SANS}font-size:12px;color:{INK};margin-top:4px;">SWS ignores dividends. Today\'s '
                 f'dividend held flat for {v.base.years} years adds <b>{money(v.dividends_pv, ccy)}</b> '
                 f'&rarr; {money(v.value_with_dividends, ccy)} ({pct(v.upside_with_dividends, signed=True)}).</div>')
    warn = "".join(f'<div style="{SANS}font-size:12px;color:{WARN};">&#9888; {esc(w)}</div>' for w in v.warnings)
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
            f'style="border:2px solid {ACCENT};border-collapse:collapse;">'
            f'{body}{foot}</table>{note}{warn}')


def company_html(r: Report, mode: str) -> str:
    a = r.analysis
    rec = a.get("publish_recommendation", r.status)
    rec_col = GOOD if rec == "PUBLISH_NEW" else WARN if rec == "UPDATE_EXISTING" else MUTED
    tc = (a.get("thesis_check") or {}).get("verdict", "")
    chips = " ".join(x for x in (
        _chip(r.portfolio.status, INK),
        _chip(rec.replace("_", " "), rec_col) if a else "",
        _chip(tc, GOOD if tc == "THESIS INTACT" else BAD) if tc else "",
        _chip(r.status, BAD) if r.status != "OK" else "",
    ) if x)
    title = a.get("title") or r.company
    rows = [
        f'<tr><td style="padding:16px 16px 2px 16px;{SANS}font-size:12px;color:{MUTED};">'
        f'{esc(r.ticker)} &middot; {esc(r.company)} &middot; {esc(a.get("event", ""))}</td></tr>',
        f'<tr><td style="padding:2px 16px 6px 16px;{FONT}font-size:21px;font-weight:bold;color:{INK};">{esc(title)}</td></tr>',
        f'<tr><td style="padding:0 16px 8px 16px;">{chips}</td></tr>',
    ]
    if r.status != "OK":
        rows.append(f'<tr><td style="padding:8px 16px;{SANS}font-size:13px;color:{BAD};">'
                    f'&#9888; {esc(r.status)}: {esc(r.error)}'
                    + (" Showing the last draft for reference, do not publish it as is." if a else "") + '</td></tr>')
        if not a:
            return _card("".join(rows))
    if a.get("publish_recommendation") == "DO_NOT_PUBLISH":
        rows.append(_section("Esther says", f"<b>Nothing material changed. Don't publish a new Narrative.</b> "
                                            f"{esc(a.get('publish_reason', ''))}"))
    rows.append(_section("Simply Wall Street inputs", _sws_html(r)))

    if mode in ("full", "thesis"):
        rows.append(_section("What changed?", _list_html(a.get("what_changed"))))
    if mode == "full":
        rows.append(_section("My read", esc(a.get("my_read", ""))))
        nums = "".join("<tr>" + _td(esc(n.get("label")), f"{SANS}font-size:12px;color:{MUTED};")
                       + _td(f"<b>{esc(n.get('value'))}</b>", f"{MONO}font-size:13px;")
                       + _td(esc(n.get("note")), f"{SANS}font-size:12px;") + "</tr>" for n in a.get("the_numbers") or [])
        rows.append(_section("The numbers",
                             f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{nums}</table>'
                             f'<div style="margin-top:6px;"><b>Statutory vs underlying:</b> {esc(a.get("statutory_vs_underlying", ""))}</div>'))
    if mode in ("full", "quick"):
        t, body = narrative_with_disclosure(r, quick=(mode == "quick"))
        rows.append(_section("Publish-ready copy" + (" (quick update)" if mode == "quick" else ""),
                             f'<div style="border-left:3px solid {ACCENT};padding:4px 0 4px 12px;">'
                             f'<div style="font-size:18px;font-weight:bold;margin-bottom:8px;">{esc(t)}</div>'
                             f'{_md_to_html(body)}</div>'))
        rows.append(_section("So what?", esc(a.get("so_what", ""))))
    if mode in ("full", "valuation"):
        rows.append(_section("Valuation", f'<b>Doing most of the work:</b> {esc(a.get("key_valuation_driver", ""))}<br>'
                                          f'<b>Biggest valuation risk:</b> {esc(a.get("biggest_valuation_risk", ""))}'
                                          + _implied_html(r)
                                          + (f'<div style="margin-top:4px;"><b>Why these inputs:</b> '
                                             f'{esc(r.valuation.narrative.rationale)}</div>' if r.valuation else "")
                                          + _stress_html(r)))
    if mode in ("full", "thesis", "challenge"):
        tcd = a.get("thesis_check") or {}
        rows.append(_section(f"Thesis check: {tcd.get('verdict', 'n/a')}",
                             esc(tcd.get("why", "")) + f'<div style="margin-top:6px;"><b>If I didn\'t already own it:</b> '
                             f'{esc(a.get("would_i_own_it_fresh", ""))}</div>'))
    if mode in ("full", "challenge"):
        ch = a.get("challenge") or {}
        items = [("Strongest argument against owning it", "strongest_argument_against"),
                 ("Weakest assumption in the valuation", "weakest_assumption"),
                 ("The number I'm most likely fooling myself with", "number_jm_is_fooling_himself_with"),
                 ("What the market may understand that I don't", "what_the_market_may_understand"),
                 ("Evidence that would force a sell/rethink", "evidence_that_forces_a_rethink")]
        rows.append(_section("Challenge my thesis (private)", "".join(
            f'<div style="margin:0 0 6px 0;"><b>{i}. {esc(lbl)}:</b> {esc(ch.get(k, ""))}</div>'
            for i, (lbl, k) in enumerate(items, 1))))
    if mode in ("full", "thesis", "challenge"):
        rows.append(_section("What would change my mind?", _list_html(a.get("what_would_change_my_mind"))))
        rows.append(_section("What I'm watching next", _list_html(a.get("watching_next"))))
    if mode == "full" and a.get("evidence"):
        ev = "".join(f'<div style="margin:0 0 5px 0;"><b>{esc(e.get("source"))}</b> ({esc(e.get("date"))}): '
                     f'{esc(e.get("fact"))} <i style="color:{MUTED};">{esc(e.get("why_it_matters"))}</i></div>'
                     for e in a["evidence"])
        gaps = "".join(f'<div style="color:{WARN};">&#9888; {esc(g)}</div>' for g in a.get("insufficient_evidence") or [])
        rows.append(_section("Evidence (for checking, not for publishing)", f'<span style="{SANS}font-size:12px;">{ev}{gaps}</span>'))
    if mode == "full" and r.qc:
        fails = [(i, n) for i, ok, n in r.qc.checks if not ok]
        qc_html = (f'<span style="color:{GOOD};">All {len(r.qc.checks)} checks passed.</span>' if not fails else
                   "".join(f'<div style="color:{WARN};">&#9744; {esc(i)}{": " + esc(n) if n else ""}</div>' for i, n in fails)
                   + f'<div style="color:{MUTED};">{len(r.qc.checks) - len(fails)} other checks passed.</div>')
        rows.append(_section("Quality control", f'<span style="{SANS}font-size:12px;">{qc_html} '
                                                f'Evidence trail and full checklist in the attached {esc(r.ticker)}.md.</span>'))
    return _card("".join(rows))


def _implied_html(r: Report) -> str:
    v = r.valuation
    if not v or v.implied_growth_at_price is None:
        return ""
    n = v.narrative
    return (f'<div style="margin-top:4px;"><b>What Mr Market is pricing in:</b> {pct(v.implied_growth_at_price)} '
            f'revenue growth a year, on the same margin ({pct(n.net_margin)}) and P/E ({n.future_pe:.1f}x).</div>')


def _stress_html(r: Report) -> str:
    v = r.valuation
    if not v or not v.stress:
        return ""
    st = v.stress
    return (f'<div style="margin-top:8px;padding:6px 8px;background:#f4f1ea;{SANS}font-size:12px;">'
            f'<b>Stress test (private, not for publishing):</b> {pct(st.revenue_growth)} growth, '
            f'{pct(st.net_margin)} margin, {st.future_pe:.1f}x &rarr; <b>{money(st.value_today, v.base.price_currency)}</b>. '
            f'{esc(st.rationale)}</div>')


def _card(inner: str) -> str:
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" '
            f'style="max-width:680px;background:{PAPER};border:1px solid {RULE};border-collapse:collapse;margin:0 0 18px 0;">'
            f'{inner}</table>')


def email_html(reports: list[Report], mode: str, run_date: str, stats: str) -> str:
    summary = "".join(
        "<tr>" + _td(f"<b>{esc(r.ticker)}</b>", SANS)
        + _td(esc((r.analysis.get("publish_recommendation") or r.status).replace("_", " ")), f"{SANS}font-size:12px;")
        + _td(esc(r.valuation and money(r.valuation.price, r.price_ccy) or "n/a"), MONO)
        + _td(esc(r.valuation and money(r.valuation.value, r.price_ccy) or "n/a"), MONO)
        + _td(esc(r.valuation and pct(r.valuation.upside, signed=True) or "n/a"), MONO)
        + "</tr>" for r in reports)
    head = "".join(_td(f"<b>{h}</b>", f"{SANS}font-size:11px;color:{MUTED};")
                   for h in ("Ticker", "Esther says", "Price", "My value", "Up/down"))
    top = (f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:680px;'
           f'background:{ACCENT};margin:0 0 12px 0;"><tr><td style="padding:16px;{FONT}color:#fff;">'
           f'<div style="font-size:24px;font-weight:bold;">Esther the Wrestler</div>'
           f'<div style="font-size:14px;font-style:italic;">She doesn\'t write the story. She finds out whether the story '
           f'survives the numbers.</div><div style="{SANS}font-size:11px;margin-top:6px;">{esc(run_date)} &middot; '
           f'mode {esc(mode.upper())} &middot; {esc(stats)}</div></td></tr></table>'
           f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:680px;'
           f'background:{PAPER};border:1px solid {RULE};margin:0 0 18px 0;"><tr>{head}</tr>{summary}</table>')
    foot = (f'<div style="{SANS}font-size:11px;color:{MUTED};max-width:680px;">Values are JM\'s valuation from the three SWS '
            f'inputs above, not "the fair value". Every input is a proposal: move the slider in Simply Wall St and '
            f'the number moves. Everything outside "Publish-ready copy" is private. The final click belongs to JM.</div>')
    return (f'<div style="background:#f4f1ea;padding:12px;">{top}'
            + "".join(company_html(r, mode) for r in reports) + foot + "</div>")


def email_text(reports: list[Report], mode: str, run_date: str, stats: str) -> str:
    out = [f"Esther the Wrestler | {run_date} | mode {mode.upper()} | {stats}", ""]
    for r in reports:
        a = r.analysis
        out += ["=" * 60, f"{r.ticker}: {a.get('title') or r.company}", f"Portfolio: {r.portfolio.status}"]
        if r.status != "OK":
            out.append(f"{r.status}: {r.error}")
        if a:
            out += [f"Esther says: {a.get('publish_recommendation', '')} {a.get('publish_reason', '')}", "",
                    sws_inputs_text(r), ""]
            if mode in ("full", "quick"):
                t, body = narrative_with_disclosure(r, quick=(mode == "quick"))
                out += ["PUBLISH-READY COPY", t, "", body, "", f"So what? {a.get('so_what', '')}", ""]
    out.append("Full detail (evidence, challenge, QC) in the attached markdown files.")
    return "\n".join(out)
