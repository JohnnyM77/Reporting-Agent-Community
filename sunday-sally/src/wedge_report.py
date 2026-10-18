"""Email-safe HTML and memo markdown for a WedgeResult.

Table-only, inline styles: no <style>, class=, flex or grid (email clients
strip or mangle them).
"""
from __future__ import annotations

from html import escape

from .value_wedge import WedgeResult, forecast_lines, low_line

_ZONE_COLOURS = {
    "Above SELL": ("#ffffff", "#c0392b"),
    "Upper third of wedge": ("#000000", "#f5b041"),
    "Middle of wedge": ("#000000", "#d6eaf8"),
    "Lower third of wedge": ("#000000", "#d5f5e3"),
    "Below BUY": ("#ffffff", "#1a7f37"),
}

_TD = "padding:4px 8px;border-bottom:1px solid #e6e5e0;font-size:13px;vertical-align:top"


def _m(v):
    return "n/a" if v is None else f"${v:,.2f}"


def wedge_html(result: WedgeResult, cid: str | None = None) -> str:
    cur = result.current
    t = escape(result.inputs.ticker.split(".")[0])
    parts = [f"<h3 style='margin:18px 0 6px 0'>{t}: the wedge between BUY and SELL</h3>"]
    if cur is None or cur.position is None:
        parts.append(f"<p>{escape(result.headline)}</p>")
        return "\n".join(parts)

    fg, bg = _ZONE_COLOURS.get(cur.zone, ("#000000", "#eeeeee"))
    ll = low_line(result)
    if ll:
        multi = ((result.price_low or {}).get("years") or 0) >= 2
        parts.append(f"<p style='margin:4px 0 8px 0;font-weight:bold;color:{'#1a7f37' if multi else '#52514e'}'>"
                     f"{escape(ll)}</p>")
    rows = [
        ("Where price sits", f"<span style='background:{bg};color:{fg};padding:2px 6px;font-weight:bold'>"
                             f"{escape(cur.zone)}</span> &nbsp;{cur.position:.0%} of the way BUY to SELL"),
        ("Share price", _m(cur.price)),
        (f"BUY value ({cur.buy_pe:g}x EPS)", _m(cur.buy_value)),
        (f"SELL value ({cur.sell_pe:g}x EPS)", _m(cur.sell_value)),
        ("Actual PE", f"{cur.actual_pe:.1f}x" if cur.actual_pe else "n/a"),
        ("EPS in force", f"{cur.eps_used:.1f}c ({escape(cur.period or '')}, {escape(result.inputs.eps_basis_label)})"),
        ("Wedge width", f"{_m(cur.abs_wedge)} per share; relative {cur.rel_wedge:.0%}"),
        ("52-week high trigger", "Fired (within 5% of high)" if result.near_52w_high else "Not fired"),
    ]
    parts.append("<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;max-width:640px'>")
    for label, val in rows:
        parts.append(f"<tr><td style='{_TD};color:#52514e;width:200px'>{escape(label)}</td>"
                     f"<td style='{_TD}'>{val}</td></tr>")
    parts.append("</table>")

    if cid:
        parts.append(f"<img src='cid:{cid}' alt='{t} value wedge chart' "
                     "style='max-width:100%;border:1px solid #cccccc;margin:10px 0'><br>")

    parts.append("<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;max-width:900px'>")
    for q, a in result.diagnostics:
        parts.append(f"<tr><td style='{_TD};font-weight:bold;width:300px'>{escape(q)}</td>"
                     f"<td style='{_TD}'>{escape(a)}</td></tr>")
    parts.append("</table>")

    if result.forecast:
        inp = result.inputs
        parts.append(f"<p style='margin:10px 0 4px 0;font-weight:bold'>Where the wedge travels: "
                     f"{escape(inp.forecast_label)} (not reported)</p>")
        if inp.forecast_basis:
            parts.append(f"<p style='font-size:12px;color:#52514e;margin:2px 0 6px 0'>{escape(inp.forecast_basis)}</p>")
        many = len(inp.forecast_cases) > 1
        parts.append("<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;max-width:900px'>")
        parts.append((f"<tr><td style='{_TD};font-weight:bold'>Case</td>" if many else "<tr>")
                     + f"<td style='{_TD};font-weight:bold'>Period</td><td style='{_TD};font-weight:bold'>EPS</td>"
                     f"<td style='{_TD};font-weight:bold'>BUY</td><td style='{_TD};font-weight:bold'>Fair</td>"
                     f"<td style='{_TD};font-weight:bold'>SELL</td>"
                     f"<td style='{_TD};font-weight:bold'>Today's price vs it</td></tr>")
        for r in result.forecast:
            pos = r.get("position_today")
            fwd = r.get("forward_pe_today")
            parts.append(
                (f"<tr><td style='{_TD}'>{escape(str(r.get('case') or ''))}</td>" if many else "<tr>")
                + f"<td style='{_TD}'>{escape(r['period'])}F<br><span style='color:#8a8985'>"
                f"{r['date']:%b %Y}</span></td><td style='{_TD}'>{r['eps_cents']:.1f}c</td>"
                f"<td style='{_TD}'>{_m(r['buy_value'])}</td><td style='{_TD}'>{_m(r.get('fair_value'))}</td>"
                f"<td style='{_TD}'>{_m(r['sell_value'])}</td>"
                f"<td style='{_TD}'>{(f'{fwd:.0f}x; ' if fwd else '')}"
                f"{escape(r['zone_today'])}{(f' ({pos:.0%})' if pos is not None else '')}</td></tr>")
        parts.append("</table>")

    parts.append(_outlook_html(result))

    if result.events:
        parts.append("<p style='margin:10px 0 4px 0;font-weight:bold'>Why the corridor moved</p>")
        parts.append("<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;max-width:900px'>")
        for i, e in enumerate(result.events, 1):
            parts.append(f"<tr><td style='{_TD};width:90px;color:#52514e'>{i}. {e.date:%b %Y}</td>"
                         f"<td style='{_TD}'>{escape(e.text)}</td></tr>")
        parts.append("</table>")
    for w in result.inputs.warnings:
        parts.append(f"<p style='font-size:12px;color:#8a8985;margin:4px 0'>Note: {escape(w)}</p>")
    return "\n".join(parts)


def _outlook_html(result: WedgeResult) -> str:
    """Two columns: why it might recover / why it might not (valuation YAML)."""
    ol = result.inputs.outlook or {}
    up, down = ol.get("recover") or [], ol.get("not_recover") or []
    if not up and not down:
        return ""

    def col(title, items, colour):
        li = "".join(f"<tr><td style='padding:3px 6px 3px 0;vertical-align:top;color:{colour}'>&#9679;</td>"
                     f"<td style='padding:3px 0;font-size:13px;vertical-align:top'>{escape(str(x))}</td></tr>"
                     for x in items)
        return (f"<td style='vertical-align:top;padding:6px 10px;width:50%;border-top:3px solid {colour}'>"
                f"<p style='margin:0 0 4px 0;font-weight:bold;color:{colour}'>{title}</p>"
                f"<table cellspacing='0' cellpadding='0' style='border-collapse:collapse'>{li}</table></td>")
    as_of = f" (as at {escape(str(ol['as_of']))})" if ol.get("as_of") else ""
    note = (f"<p style='font-size:12px;color:#8a8985;margin:4px 0'>{escape(str(ol['note']))}</p>"
            if ol.get("note") else "")
    return ("<p style='margin:12px 0 4px 0;font-weight:bold'>Does it recover? The case each way" + as_of + "</p>"
            "<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;max-width:900px'><tr>"
            + col("Why it might recover", up, "#1a7f37") + col("Why it might not", down, "#c0392b")
            + "</tr></table>" + note)


def wedge_markdown(result: WedgeResult) -> str:
    lines = ["", "## Value wedge (BUY to SELL)", f"**{result.headline}**", ""]
    ll = low_line(result)
    if ll:
        lines += [f"**{ll}**", ""]
    for q, a in result.diagnostics:
        lines.append(f"- **{q}** {a}")
    if result.forecast:
        lines += ["", f"**Where the wedge travels: {result.inputs.forecast_label} (not reported)**"]
        if result.inputs.forecast_basis:
            lines.append(result.inputs.forecast_basis)
        lines += [f"- {x}" for x in forecast_lines(result)]
    ol = result.inputs.outlook or {}
    if ol.get("recover") or ol.get("not_recover"):
        lines += ["", "**Why it might recover**"] + [f"- {x}" for x in ol.get("recover") or []]
        lines += ["", "**Why it might not**"] + [f"- {x}" for x in ol.get("not_recover") or []]
    if result.events:
        lines += ["", "**Why the corridor moved**"]
        lines += [f"{i}. {e.date:%b %Y}: {e.text}" for i, e in enumerate(result.events, 1)]
    for w in result.inputs.warnings:
        lines.append(f"\n_Note: {w}_")
    return "\n".join(lines) + "\n"
