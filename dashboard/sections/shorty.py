"""Shorty card -- ASIC short-interest. Pure rendering: takes shorty.json
(already loaded) and returns HTML. Reading/writing docs/data stays in
scripts/build_dashboard.py."""

from __future__ import annotations

from dashboard.common import _fmt_date, _esc


def _pct_html(pct, rank) -> str:
    if not isinstance(pct, (int, float)):
        return "<span style='color:#64748b'>not reported</span>"
    rank_html = f" <span style='color:#64748b;font-size:11px'>(#{rank})</span>" if rank else ""
    colour = "#ef4444" if pct >= 10 else "#f59e0b" if pct >= 5 else "#e2e8f0"
    return f"<span style='color:{colour};font-weight:600'>{pct:.2f}%</span>{rank_html}"


def _change_html(change) -> str:
    if not isinstance(change, (int, float)):
        return "<span style='color:#64748b'>n/a</span>"
    if abs(change) < 0.005:
        return "<span style='color:#64748b'>0.00pp —</span>"
    colour = "#ef4444" if change > 0 else "#22c55e"
    arrow = "▲" if change > 0 else "▼"
    sign = "+" if change > 0 else ""
    return f"<span style='color:{colour};font-weight:600'>{sign}{change:.2f}pp {arrow}</span>"


def _shorty_section(data: dict) -> str:
    run_date = _fmt_date(data.get("last_run"))
    report_date = data.get("report_date") or "—"
    baseline_date = data.get("baseline_date")
    rows = data.get("rows") or []
    top_market = data.get("top_market")
    baseline_note = data.get("baseline_unavailable_note")

    def _sort_key(r: dict):
        pct = r.get("current_pct")
        return (pct is None, -(pct or 0), r.get("ticker", ""))

    rows = sorted(rows, key=_sort_key)

    callout_html = ""
    if top_market:
        callout_html = (
            "<p style='font-size:13px;color:#cbd5e1;margin:0 0 12px 0'>Most shorted on the ASX: "
            f"<strong style='color:#fbbf24'>{_esc(top_market.get('ticker',''))}</strong> "
            f"({_esc(top_market.get('company',''))}) at "
            f"<strong>{top_market.get('pct', 0):.2f}%</strong></p>"
        )

    note_html = (
        f"<p style='font-size:11px;color:#f59e0b;margin:0 0 10px 0'>{_esc(baseline_note)}</p>"
        if baseline_note else ""
    )

    if rows:
        body_rows = "".join(
            "<tr>"
            f"<td style='color:#fbbf24;font-weight:700'>{_esc(r.get('ticker',''))}</td>"
            f"<td style='color:#cbd5e1'>{_esc(r.get('company',''))[:35]}</td>"
            f"<td style='text-align:right'>{_pct_html(r.get('current_pct'), r.get('current_rank'))}</td>"
            f"<td style='text-align:right'>{_pct_html(r.get('baseline_pct'), r.get('baseline_rank'))}</td>"
            f"<td style='text-align:right'>{_change_html(r.get('change_pp'))}</td>"
            "</tr>"
            for r in rows
        )
        table_html = (
            "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            "<tr style='color:#64748b;font-size:11px'>"
            "<th style='text-align:left'>Ticker</th><th style='text-align:left'>Company</th>"
            "<th style='text-align:right'>Current</th><th style='text-align:right'>FY-Start</th>"
            "<th style='text-align:right'>Change</th></tr>"
            f"{body_rows}</table>"
        )
    else:
        table_html = "<p style='color:#64748b'>No portfolio tickers in this report</p>"

    return f"""
    <div class="agent-card">
      <div class="card-header">
        <div>
          <span class="agent-name">Shorty</span>
          <span class="agent-role">ASX Short Interest (ASIC)</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:13px;color:#e2e8f0">Report: {_esc(report_date)}</div>
          <div style="font-size:12px;color:#64748b;margin-top:4px">Last run: {run_date}{' · FY-start baseline: ' + _esc(baseline_date) if baseline_date else ''}</div>
        </div>
      </div>
      {callout_html}
      {note_html}
      {table_html}
      <p style="font-size:11px;color:#475569;margin-top:10px">Source: ASIC daily aggregate short position reports. Figures depend on short sellers' own reporting and can be revised.</p>
    </div>"""
