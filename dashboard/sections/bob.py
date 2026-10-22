"""Bob the Bot (ASX) card, plus the analysis-card helpers Slinger and Bob USA reuse.

Pure rendering: takes the agent's docs/data JSON (already loaded) and
returns HTML. Reading and writing docs/data stays in scripts/build_dashboard.py."""

from __future__ import annotations

from dashboard.common import _esc, _fmt_date, _section_cell


# ---------------------------------------------------------------------------
# Bob section — analysis card helpers
# ---------------------------------------------------------------------------

_BADGE_COLOURS = {
    "results":        "#f59e0b",
    "acquisition":    "#8b5cf6",
    "capital":        "#3b82f6",
    "trading_update": "#06b6d4",
    "quarterly_4c":   "#14b8a6",
    "price_sensitive":"#ef4444",
    "remuneration":   "#ec4899",
}

# Results cards carry the current five-metric schema first; the long-form
# fields below it are kept so historical bob.json entries still render.
_RESULTS_FIELDS = [
    ("summary",           "Summary"),
    ("metrics",           "Key Metrics"),
    ("executive_summary", "Executive Summary"),
    ("key_numbers",       "Key Numbers"),
    ("quality_of_earnings","Quality of Earnings"),
    ("management_framing","Management Framing"),
    ("positives",         "Positives"),
    ("negatives",         "Negatives / Red Flags"),
    ("bottom_line",       "Bottom Line"),
]

_METRIC_LABELS = [
    ("revenue",             "Revenue"),
    ("underlying_npat",     "Underlying NPAT"),
    ("underlying_eps",      "Underlying EPS"),
    ("dividend_ordinary",   "Ordinary dividend"),
    ("operating_cash_flow", "Operating cash flow"),
]


def _flatten_metrics(metrics: dict) -> dict:
    """Collapse {"revenue": {"value": .., "change_pct": ..}} into a flat
    label -> "value  change" map that _section_cell can render."""
    flat = {}
    for key, label in _METRIC_LABELS:
        entry = metrics.get(key)
        if isinstance(entry, dict):
            value = str(entry.get("value", "") or "n/a")
            change = str(entry.get("change_pct", entry.get("change", "")) or "")
            flat[label] = f"{value}  {change}".strip()
        elif entry:
            flat[label] = str(entry)
    return flat
# Acquisition card. "quick_take" is the structured 5-row quick-take (target,
# consideration, multiple, funding, strategic fit) — the long-form analysis
# lives in the attached PDF, not here. Replaces the old free-text
# deal_summary/what_they_bought/... schema.
_ACQUISITION_FIELDS = [
    ("quick_take",    "Quick Take"),
    ("summary",       "Summary"),
]
# Capital/debt raise card. Structured like the results and remuneration cards:
# a verdict (opportunistic/rescue), the kind, the locked quick-take panel and
# the short summary. The long-form analysis lives in the attached PDF, not here.
_CAPITAL_FIELDS = [
    ("verdict",       "Verdict"),
    ("kind",          "Type"),
    ("quick_take",    "Quick Take"),
    ("summary",       "Summary"),
]
# Trading update card. "quick_take" is the structured 4-row quick-take
# (headline number, vs guidance, driver, balance sheet), same shape as the
# capital/debt raise card — the long-form analysis lives in the attached PDF,
# not here. Replaces the old free-text what_they_said/... schema.
_TRADING_FIELDS = [
    ("quick_take",    "Quick Take"),
    ("summary",       "Summary"),
]

# Appendix 4C / 5B quarterly cash flow card. "cash_flow" is the structured
# operating/investing/financing panel; "runway" is Question 8 — the number
# that actually matters for a small-cap holder.
_QUARTERLY_4C_FIELDS = [
    ("cash_flow",      "Cash Flow"),
    ("cash_position",  "Cash Position"),
    ("runway",         "Runway"),
    ("summary",        "Summary"),
]
_PRICE_SENSITIVE_FIELDS = [
    ("what_happened",       "What Happened"),
    ("why_price_sensitive", "Why Price Sensitive"),
    ("numbers_materiality", "Numbers & Materiality"),
    ("impact_on_thesis",    "Impact on Thesis"),
    ("risks_questions",     "Risks / Questions"),
    ("bottom_line",         "Bottom Line"),
]
# Remuneration card. "quick_take" is the structured 5-row summary (funding,
# quantum, hurdles, vesting, dilution) — flattened separately below so it
# renders as one panel rather than five nested key/value blocks.
_REMUNERATION_FIELDS = [
    ("verdict",          "Verdict"),
    ("alignment_score",  "Alignment (1-5)"),
    ("plan_type",        "Plan Type"),
    ("participants",     "Participants"),
    ("quick_take",       "Quick Take"),
    ("summary",          "Summary"),
]
_DEFAULT_FIELDS = [
    ("what_happened", "What Happened"),
    ("so_what",       "So What"),
]

_FIELD_MAP = {
    "results":        _RESULTS_FIELDS,
    "acquisition":    _ACQUISITION_FIELDS,
    "capital":        _CAPITAL_FIELDS,
    "trading_update": _TRADING_FIELDS,
    "quarterly_4c":   _QUARTERLY_4C_FIELDS,
    "price_sensitive":_PRICE_SENSITIVE_FIELDS,
    "remuneration":   _REMUNERATION_FIELDS,
}


_QUICK_TAKE_LABELS = [
    ("funding",              "Funding"),
    ("quantum",              "Quantum"),
    ("hurdles",              "Hurdles"),
    ("vesting_period",       "Vesting"),
    ("shareholder_dilution", "Dilution"),
]

# Capital/debt raise quick-take rows — kept in step with
# agent.FUNDRAISE_QUICK_TAKE_ROWS.
_FUNDRAISE_QUICK_TAKE_LABELS = [
    ("instrument",       "Type"),
    ("amount",           "Amount"),
    ("structure",        "Structure"),
    ("use_of_proceeds",  "Use of funds"),
    ("cost_or_dilution", "Cost / dilution"),
    ("balance_sheet",    "Leverage"),
]

# Trading update quick-take rows — kept in step with
# agent.TRADING_UPDATE_QUICK_TAKE_ROWS.
_TRADING_UPDATE_QUICK_TAKE_LABELS = [
    ("headline_metric", "Headline number"),
    ("guidance_call",   "vs Guidance"),
    ("key_driver",      "Driver"),
    ("balance_sheet",   "Balance sheet"),
]

# 4C cash-flow rows — kept in step with agent.QUARTERLY_4C_CASHFLOW_ROWS.
_QUARTERLY_4C_CASHFLOW_LABELS = [
    ("operating", "Operating"),
    ("investing", "Investing"),
    ("financing", "Financing"),
]

# Acquisition quick-take rows — kept in step with agent.ACQUISITION_QUICK_TAKE_ROWS.
_ACQUISITION_QUICK_TAKE_LABELS = [
    ("target",              "Target"),
    ("consideration",       "Consideration"),
    ("multiple",            "Multiple"),
    ("funding",             "Funding"),
    ("capital_raise_check", "Capital raise check"),
    ("strategic_fit",       "Strategic fit"),
]


def _flatten_cash_flow(cash_flow: dict) -> dict:
    """Collapse {"operating": {"value": .., "ytd": ..}} into a flat
    label -> "value (YTD ..)" map that _section_cell can render."""
    flat = {}
    for key, label in _QUARTERLY_4C_CASHFLOW_LABELS:
        entry = cash_flow.get(key)
        if isinstance(entry, dict):
            value = str(entry.get("value", "") or "n/a")
            ytd = str(entry.get("ytd", "") or "")
            flat[label] = f"{value}  (YTD {ytd})" if ytd and ytd != value else value
        elif entry:
            flat[label] = str(entry)
    return flat


def _flatten_single(entry) -> str:
    """{"value": .., "note": ..} -> "value — note" for a one-row panel."""
    if isinstance(entry, dict):
        value = str(entry.get("value", "") or "n/a")
        note = str(entry.get("note", "") or "")
        return f"{value} — {note}" if note else value
    return str(entry or "n/a")


def _flatten_quick_take(quick_take: dict, labels=None) -> dict:
    """Collapse {"funding": {"value": .., "note": ..}} into a flat
    label -> "value (note)" map that _section_cell can render as one panel."""
    flat = {}
    for key, label in (labels or _QUICK_TAKE_LABELS):
        entry = quick_take.get(key)
        if isinstance(entry, dict):
            value = str(entry.get("value", "") or "not disclosed")
            note = str(entry.get("note", "") or "")
            flat[label] = f"{value} — {note}" if note else value
        elif entry:
            flat[label] = str(entry)
    return flat


def _render_analysis_sections(analysis: dict, kind: str) -> str:
    fields = _FIELD_MAP.get(kind, _DEFAULT_FIELDS)

    def _value(key):
        raw = analysis.get(key)
        if key == "metrics" and isinstance(raw, dict):
            return _flatten_metrics(raw)
        if key == "quick_take" and isinstance(raw, dict):
            if kind == "capital":
                labels = _FUNDRAISE_QUICK_TAKE_LABELS
            elif kind == "trading_update":
                labels = _TRADING_UPDATE_QUICK_TAKE_LABELS
            elif kind == "acquisition":
                labels = _ACQUISITION_QUICK_TAKE_LABELS
            else:
                labels = _QUICK_TAKE_LABELS
            return _flatten_quick_take(raw, labels)
        if key == "cash_flow" and isinstance(raw, dict):
            return _flatten_cash_flow(raw)
        if key in ("cash_position", "runway") and isinstance(raw, dict):
            return _flatten_single(raw)
        return raw

    cells = "".join(_section_cell(label, _value(key)) for key, label in fields)
    return (
        f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));"
        f"gap:8px;padding:12px 14px 14px'>{cells}</div>"
    )


def _hi_item_card(item: dict) -> str:
    ticker = _esc(item.get("ticker", ""))
    title  = _esc(item.get("title", "")[:120])
    url    = item.get("url", "")
    itype  = item.get("type", "")
    badge_bg = _BADGE_COLOURS.get(itype, "#64748b")
    type_label = itype.replace("_", " ").upper() if itype else "HIGH IMPACT"
    analysis = item.get("analysis")

    header = (
        f"<div style='background:#1a2540;padding:10px 14px;display:flex;"
        f"justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px'>"
        f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap'>"
        f"<strong style='color:#fbbf24;font-size:14px'>{ticker}</strong>"
        f"<span style='background:{badge_bg};color:#fff;padding:1px 7px;border-radius:3px;"
        f"font-size:10px;white-space:nowrap'>{type_label}</span>"
        f"<span style='color:#cbd5e1;font-size:12px'>{title}</span>"
        f"</div>"
        f"<div style='display:flex;align-items:center;gap:10px;white-space:nowrap'>"
        + (
            f"<a href='{item.get('doc_link')}' target='_blank' style='color:#34d399;"
            f"font-size:12px'>Full analysis ↗</a>" if item.get("doc_link") else ""
        )
        + f"<a href='{url}' target='_blank' style='color:#60a5fa;font-size:12px'>Open ↗</a>"
        f"</div>"
        f"</div>"
    )

    if analysis:
        sections_html = _render_analysis_sections(analysis, itype)
        body = (
            f"<details open style='border-top:1px solid #334155'>"
            f"<summary style='cursor:pointer;padding:7px 14px;color:#94a3b8;font-size:11px;"
            f"list-style:none;user-select:none'>▸ Analysis</summary>"
            f"{sections_html}"
            f"</details>"
        )
    else:
        body = ""

    return (
        f"<div style='border:1px solid #334155;border-radius:8px;overflow:hidden;margin:10px 0'>"
        f"{header}{body}"
        f"</div>"
    )


def _mat_item_row(item: dict) -> str:
    ticker = _esc(item.get("ticker", ""))
    title  = _esc(item.get("title", "")[:120])
    url    = item.get("url", "")
    analysis = item.get("analysis", {})
    what = _esc(str(analysis.get("what_happened", title)))
    so_what = _esc(str(analysis.get("so_what", "")))
    detail = (
        f"<div style='color:#e2e8f0'>{what}</div>"
        f"<div style='color:#94a3b8;font-size:11px;margin-top:3px'>→ {so_what}</div>"
        if so_what else f"<div style='color:#e2e8f0'>{what}</div>"
    )
    return (
        f"<tr>"
        f"<td style='white-space:nowrap'><strong style='color:#60a5fa'>{ticker}</strong></td>"
        f"<td>{detail}</td>"
        f"<td style='white-space:nowrap'>"
        f"<a href='{url}' target='_blank' style='color:#60a5fa;font-size:11px'>Open ↗</a>"
        f"</td>"
        f"</tr>"
    )


# ---------------------------------------------------------------------------
# Bob section
# ---------------------------------------------------------------------------

def _bob_run_blocks(data: dict) -> str:
    """The high-impact / material / FYI blocks for one Bob run.

    Pulled out of ``_bob_section`` so the same rendering serves both the
    current digest and the retained previous one.
    """
    hi = data.get("high_impact", [])
    mat = data.get("material", [])
    fyi = data.get("fyi", [])

    hi_cards = "".join(_hi_item_card(item) for item in hi)

    mat_rows = "".join(_mat_item_row(item) for item in mat[:10])
    if len(mat) > 10:
        mat_rows += (
            f"<tr><td colspan='3' style='color:#64748b;font-size:11px;padding:6px 0'>"
            f"… and {len(mat)-10} more material items</td></tr>"
        )

    fyi_rows = "".join(
        f"<tr>"
        f"<td><strong style='color:#94a3b8'>{_esc(item.get('ticker',''))}</strong></td>"
        f"<td style='color:#94a3b8;font-size:12px'>{_esc(item.get('title','')[:100])}</td>"
        f"<td><a href='{item.get('url','')}' target='_blank' style='color:#60a5fa;font-size:11px'>Open</a></td>"
        f"</tr>"
        for item in fyi[:15]
    )
    if len(fyi) > 15:
        fyi_rows += (
            f"<tr><td colspan='3' style='color:#64748b;font-size:11px'>"
            f"… and {len(fyi)-15} more FYI items</td></tr>"
        )

    _no_hi   = "<p style='color:#64748b;font-size:13px'>No high-impact announcements</p>"
    _no_mat  = "<tr><td style='color:#64748b;padding:6px 0'>No material announcements</td></tr>"
    _no_fyi  = "<tr><td style='color:#64748b;padding:6px 0'>No announcements today</td></tr>"

    hi_block = (
        f"<h4 style='color:#fbbf24;margin:16px 0 6px'>⚡ HIGH IMPACT ({len(hi)})</h4>"
        + (hi_cards if hi_cards else _no_hi)
    ) if hi else ""

    mat_block = (
        f"<h4 style='color:#3b82f6;margin:16px 0 6px'>📌 MATERIAL ({len(mat)})</h4>"
        f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        + (mat_rows if mat_rows else _no_mat)
        + "</table>"
    ) if mat else ""

    fyi_block = (
        f"<h4 style='color:#10b981;margin:16px 0 6px'>📋 FYI — ALL ANNOUNCEMENTS ({len(fyi)})</h4>"
        f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        + (fyi_rows if fyi_rows else _no_fyi)
        + "</table>"
    )

    return hi_block + mat_block + fyi_block

def _bob_section(data: dict, history: list[dict] | None = None) -> str:
    """Bob's card: the current digest, plus the previous run kept below it.

    ``history`` is the rolling list written by ``_update_bob_history`` —
    newest first, current run at index 0, at most two entries. The previous
    run is rendered collapsed so the page stays a glance while the last two
    iterations are both there. Falls back to just ``data`` when no history is
    available.
    """
    run_date = _fmt_date(data.get("last_run"))
    hi = data.get("high_impact", [])
    silence = data.get("silence", False)

    status_dot = "#ef4444" if hi else "#22c55e"
    status_text = f"{len(hi)} HIGH IMPACT" if hi else ("SILENCE" if silence else "All clear")

    current_blocks = _bob_run_blocks(data)

    previous_html = ""
    prior = (history or [])[1:2]
    if prior:
        prev = prior[0]
        prev_date = _fmt_date(prev.get("last_run"))
        prev_hi = len(prev.get("high_impact", []))
        prev_mat = len(prev.get("material", []))
        prev_fyi = len(prev.get("fyi", []))
        previous_html = (
            "<details style='margin-top:20px;border-top:1px solid #334155;padding-top:12px'>"
            "<summary style='cursor:pointer;color:#94a3b8;font-size:13px;font-weight:600'>"
            f"◷ Previous digest — {prev_date} "
            f"<span style='color:#64748b;font-weight:400'>"
            f"({prev_hi} high-impact · {prev_mat} material · {prev_fyi} FYI)</span>"
            "</summary>"
            "<div style='margin-top:10px;opacity:0.85'>"
            + _bob_run_blocks(prev)
            + "</div></details>"
        )

    return f"""
    <div class="agent-card">
      <div class="card-header">
        <div>
          <span class="agent-name">Bob the Bot</span>
          <span class="agent-role">Daily ASX Digest &middot; last two runs kept</span>
        </div>
        <div style="text-align:right">
          <div><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{status_dot};margin-right:6px"></span><span style="font-size:13px;color:#e2e8f0">{status_text}</span></div>
          <div style="font-size:12px;color:#64748b;margin-top:4px">Last run: {run_date}</div>
        </div>
      </div>
      {current_blocks}
      {previous_html}
    </div>"""
