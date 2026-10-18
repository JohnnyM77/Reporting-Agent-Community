"""Harry Hindsight card: verdicts, the thesis ledger, percentages only.

Pure rendering: takes the agent's docs/data JSON (already loaded) and
returns HTML. Reading and writing docs/data stays in scripts/build_dashboard.py."""

from __future__ import annotations

from dashboard.common import _esc, _fmt_date
from shared.public_safety import scrub_obj


# ---------------------------------------------------------------------------
# Harry Hindsight section — the Chief Sceptic's verdicts (public-safe summary)
# ---------------------------------------------------------------------------

_HARRY_SEVERITY = {"GREEN": "#22c55e", "AMBER": "#f59e0b", "RED": "#ef4444", "LOLLAPALOOZA": "#a78bfa"}
_HARRY_TYPES = {"SELL_ALERT": "Sell alert", "BOB_REVIEW": "Event review",
                "WALLY_REVIEW": "Opportunity review", "PORTFOLIO_REVIEW": "Portfolio review"}


_THESIS_COLOUR = {"BROKEN": "#ef4444", "WEAKENED": "#f59e0b", "CHANGED": "#f59e0b",
                  "THESIS INTACT": "#22c55e", "STRENGTHENED": "#22c55e"}
_PILLAR_COLOUR = {"BREACHED": "#ef4444", "STRAINED": "#f59e0b", "INTACT": "#22c55e"}


def _pct(v, signed: bool = True) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.0f}%" if signed else f"{v:.1f}%"


def _ledger_html(ledger: dict) -> str:
    """Harry's latest read of every holding's thesis. No dollar figures."""
    # The site is public: no position weights, and model-written prose is
    # scrubbed of any weight, share count or position-sized dollar figure.
    rows = scrub_obj(ledger.get("theses", []) or [])
    if not rows:
        return ""
    th = "color:#64748b;font-size:11px;text-align:left;padding:4px 6px;font-weight:600"
    td = "font-size:12px;color:#e2e8f0;padding:5px 6px;border-top:1px solid #1e293b;vertical-align:top"
    body = ""
    for r in rows:
        cls = str(r.get("thesis") or "n/a")
        c = _THESIS_COLOUR.get(cls, "#64748b")
        pillars = " ".join(
            f"<span style='color:{_PILLAR_COLOUR.get(st, '#94a3b8')}'>{_esc(pid)}</span>"
            for pid, st in (r.get("pillars") or {}).items())
        body += (
            f"<tr><td style='{td};font-weight:700;color:#fbbf24'>{_esc(r.get('ticker', ''))}</td>"
            f"<td style='{td};color:{c};font-weight:700'>{_esc(cls)}</td>"
            f"<td style='{td}'>{pillars}</td>"
            f"<td style='{td}'>{_esc(r.get('severity', ''))}</td>"
            f"<td style='{td};text-align:right'>{_esc(_pct(r.get('unrealised_pct')))}</td>"
            f"<td style='{td};color:#c4b5fd'>{_esc(', '.join(r.get('biases') or []))}</td></tr>")
    heads = "".join(f"<th style='{th}'>{h}</th>" for h in
                    ("Ticker", "Thesis", "Pillars", "Severity", "vs cost", "Munger biases with evidence"))
    return (
        "<div style='margin-top:14px'><div style='color:#e2e8f0;font-size:13px;font-weight:700'>Thesis ledger"
        f" <span style='color:#64748b;font-weight:400;font-size:12px'>updated {_esc(_fmt_date(ledger.get('updated')))}"
        " · Theo records a BROKEN read as an open question</span></div>"
        "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;margin-top:6px'>"
        f"<tr>{heads}</tr>{body}</table></div></div>")


def _harry_section(data: dict, ledger: dict | None = None) -> str:
    reports = scrub_obj(data.get("reports", []) or [])
    run_date = _fmt_date(data.get("last_run"))
    if not reports:
        body = "<p style='color:#64748b;font-size:13px;margin-top:12px'>No reports yet.</p>"
    else:
        cards = ""
        for i, r in enumerate(reports[:8]):
            sev = str(r.get("severity", ""))
            colour = _HARRY_SEVERITY.get(sev, "#64748b")
            rows = []
            if r.get("thesis"):
                rows.append(("Thesis", str(r["thesis"]).title()))
            if r.get("would_buy_today"):
                rows.append(("Would buy it today?", r["would_buy_today"]))
            if r.get("would_rebuy"):
                rows.append(("Want it back if forced out?", r["would_rebuy"]))
            rows.append(("Lollapalooza", "YES" if r.get("lollapalooza") else "No"))
            if r.get("biases"):
                rows.append(("Biases with evidence", ", ".join(r["biases"])))
            pos = r.get("position") or {}
            if pos.get("unrealised_pct") is not None:
                rows.append(("Position vs cost", _pct(pos["unrealised_pct"])))
            rows_html = "".join(
                f"<tr><td style='color:#94a3b8;font-size:12px;padding:3px 0'>{_esc(k)}</td>"
                f"<td style='text-align:right;color:#e2e8f0;font-size:12px;font-weight:700;padding:3px 0'>{_esc(str(v))}</td></tr>"
                for k, v in rows)
            extra = ""
            for d in r.get("disagreements", []) or []:
                extra += (f"<div style='font-size:12px;color:#c4b5fd;margin-top:6px'>Disagrees with "
                          f"{_esc(str(d.get('with','')).title())}: {_esc(d.get('point',''))}</div>")
            mind = r.get("what_would_change_my_mind") or []
            if mind:
                extra += ("<div style='font-size:12px;color:#94a3b8;margin-top:8px'>What would change the call:</div><ul style='margin:2px 0 0 16px;font-size:12px;color:#cbd5e1'>"
                          + "".join(f"<li>{_esc(m)}</li>" for m in mind) + "</ul>")
            inner = (
                f"<div style='display:flex;justify-content:space-between;align-items:center'>"
                f"<div><strong style='color:#fbbf24;font-size:15px'>{_esc(r.get('ticker',''))}</strong>"
                f" <span style='color:#94a3b8;font-size:12px'>{_esc(_HARRY_TYPES.get(r.get('report_type',''), r.get('report_type','')))}"
                f" · {_esc(_fmt_date(r.get('date')))}</span></div>"
                f"<span style='background:{colour};color:#0b1220;font-size:10px;font-weight:800;padding:2px 8px;border-radius:5px'>{_esc(sev)}</span></div>"
                f"<div style='color:#e2e8f0;font-size:14px;font-weight:700;margin:8px 0 4px'>{_esc(r.get('verdict',''))}</div>"
                f"<div style='color:#94a3b8;font-size:12px;line-height:1.5'>{_esc(r.get('severity_reason',''))}</div>"
                f"<table style='width:100%;border-collapse:collapse;margin-top:8px'>{rows_html}</table>{extra}"
            )
            box = f"<div style='background:#0f172a;border-left:3px solid {colour};border-radius:8px;padding:12px 14px;margin-top:10px'>{inner}</div>"
            if i == 0:
                cards += box
            else:
                cards += f"<details style='margin-top:6px'><summary style='cursor:pointer;color:#94a3b8;font-size:12px'>{_esc(r.get('ticker',''))} · {_esc(sev)} · {_esc(_fmt_date(r.get('date')))}</summary>{box}</details>"
        body = cards
    return f"""
    <div class="agent-card">
      <div class="card-header">
        <div>
          <span class="agent-name">Harry Hindsight</span>
          <span class="agent-role">Chief Sceptic · looking through Harry's ass has 20:20 vision</span>
        </div>
        <div style="text-align:right">
          <div style="font-size:13px;color:#e2e8f0">{len(reports)} report(s)</div>
          <div style="font-size:12px;color:#64748b;margin-top:4px">Last run: {run_date}</div>
        </div>
      </div>
      {_ledger_html(ledger or {})}
      {body}
    </div>"""
