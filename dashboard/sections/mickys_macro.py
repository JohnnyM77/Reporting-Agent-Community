"""Micky's Macro card: trend dossiers and company candidates, public-safe.

Pure rendering: takes docs/data/mickys_macro.json (already loaded) and
returns HTML. Reading/writing docs/data stays in scripts/build_dashboard.py."""

from __future__ import annotations

from dashboard.common import _esc, _fmt_date

_EXPOSURE_COLOUR = {
    "DIRECT_BENEFICIARY": "#22c55e",
    "BOTTLENECK_SUPPLIER": "#38bdf8",
    "ENABLER": "#a78bfa",
    "POTENTIAL_LOSER": "#ef4444",
}
_SECULAR_COLOUR = {
    "SECULAR": "#22c55e",
    "CYCLICAL_REBOUND": "#f59e0b",
    "SPECULATIVE_NARRATIVE": "#ef4444",
    "UNDETERMINED": "#64748b",
}


def _dossier_card(d: dict) -> str:
    cls = str(d.get("secular_or_cyclical", "UNDETERMINED"))
    colour = _SECULAR_COLOUR.get(cls, "#64748b")
    scorecard = d.get("scorecard") or {}
    score_rows = ""
    for key, dim in scorecard.items():
        label = key.replace("_", " ").title()
        score_rows += (
            f"<tr><td style='color:#94a3b8;font-size:11px;padding:2px 0'>{_esc(label)}</td>"
            f"<td style='text-align:right;color:#e2e8f0;font-size:11px;font-weight:700;padding:2px 0'>"
            f"{_esc(dim.get('score'))}/10</td></tr>"
        )
    winners = ", ".join(d.get("winners") or []) or "n/a"
    inner = (
        f"<div style='display:flex;justify-content:space-between;align-items:center'>"
        f"<strong style='color:#fbbf24;font-size:14px'>{_esc(d.get('name',''))}</strong>"
        f"<span style='background:{colour};color:#0b1220;font-size:10px;font-weight:800;"
        f"padding:2px 8px;border-radius:5px'>{_esc(cls)}</span></div>"
        f"<div style='color:#94a3b8;font-size:12px;margin-top:6px'>{_esc((d.get('thesis') or '')[:220])}</div>"
        f"<div style='color:#64748b;font-size:11px;margin-top:6px'>Winners named so far: {_esc(winners)}</div>"
        + (f"<table style='width:100%;border-collapse:collapse;margin-top:8px'>{score_rows}</table>" if score_rows else "")
    )
    return f"<div style='background:#0f172a;border-left:3px solid {colour};border-radius:8px;padding:12px 14px;margin-top:10px'>{inner}</div>"


def _candidate_row(c: dict) -> str:
    colour = _EXPOSURE_COLOUR.get(str(c.get("exposure_type")), "#64748b")
    v = c.get("valuation") or {}
    pe = v.get("pe")
    pe_txt = f"{pe:.1f}x" if isinstance(pe, (int, float)) else (v.get("not_covered_reason") or "n/a")
    overlap = ", ".join(c.get("portfolio_overlap") or []) or "no overlap found"
    td = "font-size:12px;color:#e2e8f0;padding:5px 6px;border-top:1px solid #1e293b;vertical-align:top"
    return (
        f"<tr><td style='{td};font-weight:700;color:#fbbf24'>{_esc(c.get('ticker',''))}</td>"
        f"<td style='{td};color:{colour}'>{_esc(str(c.get('exposure_type','')).replace('_',' ').title())}</td>"
        f"<td style='{td}'>{_esc(pe_txt)}</td>"
        f"<td style='{td};color:#94a3b8'>{_esc(overlap)}</td></tr>"
    )


def _mickys_macro_section(data: dict) -> str:
    dossiers = data.get("dossiers", []) or []
    candidates = data.get("candidates", []) or []
    run_date = _fmt_date(data.get("last_run"))
    processing = data.get("processing") or {}

    if not dossiers:
        body = "<p style='color:#64748b;font-size:13px;margin-top:12px'>No trend dossiers yet.</p>"
    else:
        body = "".join(_dossier_card(d) for d in dossiers[:8])

    cand_html = ""
    if candidates:
        heads = "".join(
            f"<th style='color:#64748b;font-size:11px;text-align:left;padding:4px 6px;font-weight:600'>{h}</th>"
            for h in ("Ticker", "Exposure", "P/E", "Portfolio overlap")
        )
        rows = "".join(_candidate_row(c) for c in candidates[:15])
        cand_html = (
            "<div style='margin-top:14px'><div style='color:#e2e8f0;font-size:13px;font-weight:700'>"
            "Company candidates</div>"
            f"<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;margin-top:6px'>"
            f"<tr>{heads}</tr>{rows}</table></div></div>"
        )

    failures = processing.get("failures") or []
    fail_html = ""
    if failures:
        fail_html = (
            "<div style='margin-top:10px;color:#f59e0b;font-size:11px'>"
            f"{processing.get('failed', 0)} processing failure(s) this run -- a half-broken run is "
            "shown as such, never silently.</div>"
        )

    return f"""
    <div class="agent-card">
      <div class="card-header">
        <div>
          <span class="agent-name">Micky's Macro</span>
          <span class="agent-role">Structural trends &amp; investment intelligence</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:13px;color:#e2e8f0">{len(dossiers)} dossier(s) · {len(candidates)} candidate(s)</div>
          <div style="font-size:12px;color:#64748b;margin-top:4px">Last run: {run_date}</div>
        </div>
      </div>
      {body}
      {cand_html}
      {fail_html}
    </div>"""
