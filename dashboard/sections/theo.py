"""Theo thesis-accountability card.

Pure rendering: takes the agent's docs/data JSON (already loaded) and
returns HTML. Reading and writing docs/data stays in scripts/build_dashboard.py."""

from __future__ import annotations

from dashboard.common import _esc, _fmt_date


# ---------------------------------------------------------------------------
# Theo section — thesis accountability
# ---------------------------------------------------------------------------

_VERDICT_COLOUR = {"DRIFTING": "#ef4444", "WATCH": "#f59e0b", "CLEAN": "#22c55e", "CLOSED": "#64748b"}
_PILLAR_COLOUR = {"INTACT": "#22c55e", "STRAINED": "#f59e0b", "BREACHED": "#ef4444"}


def _theo_link(ticker: str, label: str | None = None) -> str:
    """A ticker that takes you to its slide.

    Theo's site reads a #TICKER/version fragment on load, so a plain relative
    link is enough — no JavaScript on this side, and any thesis added later
    gets a working link with no further work, because this card is generated
    from theo.json.
    """
    ticker = _esc(ticker)
    return (
        f"<a href='theo/#{ticker}/current' "
        f"style='color:#fbbf24;text-decoration:none;border-bottom:1px dotted #a16207'>"
        f"{_esc(label) if label else ticker}</a>"
    )


_TRIGGER_LABEL = {
    "SALLY_TRIM": "Sally: trim",
    "SALLY_REVIEW": "Sally: review",
    "HARRY_BROKEN": "Harry: thesis broken",
    "ANNUAL_REPORT": "Annual refresh",
    "ANNUAL": "Annual refresh",
    "ANNUAL_REFRESH": "Annual refresh",
}
_DECISION_COLOUR = {
    "ACTED": "#22c55e", "PARTIAL": "#3b82f6", "DECLINED": "#f59e0b", "RECORDED": "#64748b",
}


def _maintenance_html(data: dict) -> str:
    """The upkeep half of the card: the annual-refresh schedule and the
    record of why a holding was kept when an agent said sell.

    Structural facts only — ticker, date, trigger, decision, reporting basis.
    The reasoning lives on the slide; nothing here can size the book."""
    m = data.get("maintenance") or {}
    annual = m.get("annual_reviews") or []
    holds = m.get("hold_decisions") or []
    if not annual and not holds:
        return ""

    due = [a for a in annual if a.get("due")]
    annual_html = ""
    if annual:
        due_rows = ""
        for a in due:
            last = _esc(a.get("last_review") or "never reviewed")
            due_rows += (
                "<div style='display:flex;justify-content:space-between;gap:8px;"
                "padding:6px 10px;margin-top:6px;background:#0f172a;border-left:3px solid #f59e0b'>"
                f"<span><strong>{_theo_link(a.get('ticker',''))}</strong>"
                f"<span style='color:#64748b;font-size:11px'> &middot; {_esc(a.get('basis',''))}</span></span>"
                f"<span style='color:#fbbf24;font-size:11px'>refresh due &middot; result ~{_esc(a.get('cycle_report_date',''))} &middot; last {last}</span>"
                "</div>"
            )
        on_track = [a for a in annual if not a.get("due")]
        schedule = " &nbsp; ".join(
            f"<span style='color:#94a3b8'>{_esc(a.get('ticker',''))}</span>"
            f"<span style='color:#475569;font-size:10px'> {_esc(a.get('basis','').split(',')[0])}</span>"
            for a in on_track
        )
        count_line = (
            f"<span style='color:#f59e0b;font-weight:700'>{len(due)} due</span>"
            if due else "<span style='color:#22c55e'>all on schedule</span>"
        )
        annual_html = (
            "<div style='margin-top:14px'>"
            "<div style='color:#94a3b8;font-size:11px;font-weight:700;letter-spacing:0.08em;"
            f"text-transform:uppercase'>Annual refresh &middot; {count_line}</div>"
            f"{due_rows}"
            + (f"<div style='color:#64748b;font-size:11px;margin-top:8px'>On schedule: {schedule}</div>"
               if schedule else "")
            + "</div>"
        )

    holds_html = ""
    if holds:
        rows = ""
        for h in holds[:12]:
            dec = _esc(h.get("decision", ""))
            trig = _TRIGGER_LABEL.get(h.get("trigger", ""), _esc(h.get("trigger", "")))
            rows += (
                "<tr>"
                f"<td><strong>{_theo_link(h.get('ticker',''))}</strong></td>"
                f"<td style='color:#94a3b8;font-size:12px'>{_esc(h.get('date',''))}</td>"
                f"<td style='color:#cbd5e1;font-size:12px'>{trig}</td>"
                f"<td><span style='color:{_DECISION_COLOUR.get(h.get('decision',''),'#64748b')};"
                f"font-size:11px;font-weight:700'>{dec}</span></td>"
                "</tr>"
            )
        holds_html = (
            "<div style='margin-top:16px'>"
            "<div style='color:#94a3b8;font-size:11px;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase'>Held when told to sell &middot; on the record</div>"
            "<table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:6px'>"
            "<tr style='color:#64748b;font-size:11px'><th style='text-align:left'>Ticker</th>"
            "<th style='text-align:left'>Date</th><th style='text-align:left'>Trigger</th>"
            "<th style='text-align:left'>Call</th></tr>"
            f"{rows}</table></div>"
        )

    return annual_html + holds_html


def _theo_section(data: dict) -> str:
    """Theo on the dashboard is a glance, not the analysis.

    Drift verdicts, unanswered questions from the other agents, and holdings
    with capital and no written reason. The slides live at /theo/ — a page
    each, which is not a dashboard thing.
    """
    if not data:
        return ""

    run_date = _fmt_date(data.get("last_run"))
    rows_in = data.get("theses", [])
    questions = data.get("open_questions", [])
    no_thesis = data.get("no_thesis", [])
    drifting = data.get("drifting", 0)

    status_dot = (
        "#ef4444" if drifting or questions else "#f59e0b" if data.get("watch") else "#22c55e"
    )

    # --- open questions come first: they are the part that needs an answer
    questions_html = ""
    if questions:
        items = ""
        for q in questions:
            items += (
                f"<div style='border-left:3px solid #f59e0b;padding:8px 12px;margin-top:8px;background:#0f172a'>"
                f"<div><strong>{_theo_link(q.get('ticker',''))}</strong>"
                f"<span style='color:#64748b;font-size:12px'> &middot; {_esc(q.get('source',''))}"
                f" &middot; {_esc(q.get('date') or '')}</span></div>"
                f"<div style='color:#94a3b8;font-size:12px;margin-top:3px'>{_esc(q.get('detail',''))}</div>"
                f"<div style='color:#e2e8f0;font-size:13px;margin-top:5px'>{_esc(q.get('question',''))}</div>"
                f"</div>"
            )
        questions_html = (
            "<div style='margin-top:12px'>"
            "<div style='color:#f59e0b;font-size:11px;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase'>Unanswered &mdash; silence is recorded</div>"
            f"{items}</div>"
        )

    # --- the thesis table
    table = ""
    if rows_in:
        rows = ""
        for r in rows_in:
            pills = "".join(
                f"<span style=\"color:{_PILLAR_COLOUR.get(p.get('status',''), '#64748b')}\" "
                f"title=\"{_esc(p.get('id',''))}: {_esc(p.get('status',''))}\">"
                f"{p.get('symbol','?')}</span>"
                for p in r.get("pillars", [])
            )
            irr = r.get("irr")
            irr_str = f"{irr * 100:.1f}%" if isinstance(irr, (int, float)) else "&mdash;"
            mult = r.get("multiple")
            mult_str = f"{mult:.2f}x" if isinstance(mult, (int, float)) else "&mdash;"
            # A closed position is not "clean" — the drift engine has nothing
            # live to watch. Show CLOSED so an exited holding never reads like
            # an all-clear on an open one.
            verdict = "CLOSED" if r.get("exited") else r.get("verdict", "")
            draft = (
                " <span style='color:#64748b;font-size:10px;border:1px solid #475569;"
                "padding:1px 4px;border-radius:3px'>DRAFT</span>"
                if r.get("draft")
                else ""
            )
            rows += (
                f"<tr>"
                f"<td><strong>{_theo_link(r.get('ticker',''))}</strong>{draft}</td>"
                f"<td style='color:#cbd5e1;font-size:12px'>"
                f"{_esc(r.get('archetype','').replace('_',' ').title())}</td>"
                f"<td style='letter-spacing:2px;font-size:14px'>{pills}</td>"
                f"<td style='text-align:center;color:#94a3b8;font-size:12px'>{_esc(r.get('grade',''))}</td>"
                f"<td style='text-align:right;color:#e2e8f0;font-size:12px'>{irr_str}</td>"
                f"<td style='text-align:right;color:#94a3b8;font-size:12px'>{mult_str}</td>"
                f"<td><span style='color:{_VERDICT_COLOUR.get(verdict, '#64748b')};font-size:11px;"
                f"font-weight:700;letter-spacing:0.06em'>{_esc(verdict)}</span></td>"
                f"</tr>"
            )
        table = f"""
        <table style='width:100%;border-collapse:collapse;font-size:13px;margin-top:12px'>
          <tr style='color:#64748b;font-size:11px'>
            <th style='text-align:left'>Ticker</th><th style='text-align:left'>Archetype</th>
            <th style='text-align:left'>Pillars</th><th style='text-align:center'>Grade</th>
            <th style='text-align:right'>IRR</th><th style='text-align:right'>Multiple</th>
            <th style='text-align:left'>Drift</th>
          </tr>
          {rows}
        </table>"""
    else:
        table = (
            "<p style='color:#64748b;font-size:13px;margin-top:12px'>"
            "No theses written yet.</p>"
        )

    gaps_html = ""
    if no_thesis:
        names = ", ".join(_esc(g.get("ticker", "")) for g in no_thesis)
        gaps_html = (
            "<div style='margin-top:14px;padding:8px 12px;background:#0f172a;"
            "border-left:3px solid #ef4444'>"
            "<span style='color:#f87171;font-size:12px;font-weight:600'>Flagged with no thesis: </span>"
            f"<span style='color:#e2e8f0;font-size:12px'>{names}</span>"
            "<div style='color:#64748b;font-size:11px;margin-top:3px'>"
            "Capital committed, a signal raised, and no written reason to own it.</div>"
            "</div>"
        )

    return f"""
    <div class="agent-card">
      <div class="card-header">
        <div>
          <span class="agent-name">Theo &mdash; Thesis Accountability</span>
          <span class="agent-role">Keeping the bastard honest &middot; <a href="theo/" style="color:#3b82f6;text-decoration:none">slides &rarr;</a></span>
        </div>
        <div style="text-align:right">
          <div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{status_dot};margin-right:6px"></span><span style="font-size:13px;color:#e2e8f0">{len(questions)} open &middot; {drifting} drifting</span></div>
          <div style="font-size:12px;color:#64748b;margin-top:4px">Last run: {run_date}</div>
        </div>
      </div>
      {questions_html}
      {table}
      {_maintenance_html(data)}
      {gaps_html}
    </div>"""
