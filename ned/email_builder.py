# ned/email_builder.py
#
# Builds the plain-text and HTML email digest for Ned the News Agent.
# Mirrors Bob's dark-navy colour scheme.

from __future__ import annotations

import html as htmlmod
import datetime as dt

from ned.source_quality import LOW_QUALITY_TIER, low_quality_rollup

COLOR_BG = "#0B1220"
COLOR_TEXT = "#E5E7EB"
COLOR_PANEL = "#1E293B"
COLOR_YOUTUBE = "#EF4444"   # red
COLOR_NEWS = "#3B82F6"      # blue
COLOR_SILENCE = "#6B7280"   # grey
COLOR_NEWSLETTER = "#A78BFA"  # violet

# Importance level colors
COLOR_CRITICAL = "#DC2626"  # red
COLOR_HIGH = "#F59E0B"      # amber
COLOR_MEDIUM = "#3B82F6"    # blue
COLOR_LOW = "#10B981"       # green
COLOR_FYI = "#6B7280"       # grey


FONT_STACK = "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif"


# ----------------------------
# Table building blocks
# ----------------------------
# Every coloured box is a table cell with both a bgcolor attribute and an
# inline background-color. Desktop Outlook (and Outlook.com in some views)
# only half-paints <div> backgrounds: each line got its own dark strip with
# the white page showing between them, which is what made the PC version
# hard to read. Table cells are painted solid by every client. Phone clients
# render these exactly like the old divs (same colours, padding and gaps), so
# the mobile look is unchanged.
def _box(inner: str, bg: str, pad: str = "12px", extra_style: str = "") -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{bg}" style="width:100%;background-color:{bg};border-collapse:separate;'
        f'border-radius:10px;{extra_style}">'
        f'<tr><td bgcolor="{bg}" style="background-color:{bg};padding:{pad};border-radius:10px;'
        f'font-family:{FONT_STACK};">{inner}</td></tr></table>'
    )


def _gap(px: int) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td height="{px}" style="height:{px}px;font-size:0;line-height:0;">&nbsp;</td></tr></table>'
    )


def _importance_badge(importance_level: str) -> str:
    """Generate an importance badge with appropriate color."""
    color_map = {
        "CRITICAL": COLOR_CRITICAL,
        "HIGH": COLOR_HIGH,
        "MEDIUM": COLOR_MEDIUM,
        "LOW": COLOR_LOW,
        "FYI": COLOR_FYI,
    }
    color = color_map.get(importance_level, COLOR_FYI)
    return (
        f'<span style="display:inline-block;background:{color};color:#FFFFFF;'
        f'font-size:10px;font-weight:800;padding:3px 8px;border-radius:6px;'
        f'margin-right:6px;letter-spacing:0.5px;">{htmlmod.escape(importance_level)}</span>'
    )


def _ticker_badges(tickers: list[str]) -> str:
    badges = ""
    for t in tickers:
        badges += (
            f'<span style="display:inline-block;background:#334155;color:#94A3B8;'
            f'font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;'
            f'margin-right:4px;">{htmlmod.escape(t)}</span>'
        )
    return badges


def _hit_html(hit: dict, llm_summary: str | None) -> str:
    tickers_str = ", ".join(hit["tickers"])
    title = htmlmod.escape(hit["title"])
    url = htmlmod.escape(hit["url"])
    source = htmlmod.escape(hit["source"])
    
    # Add importance badge if present - inline with ticker badges
    importance_badge = ""
    if "importance_level" in hit:
        importance_badge = _importance_badge(hit["importance_level"])
    
    also = hit.get("also_covered_by") or []
    also_block = ""
    if also:
        also_block = (
            f'<div style="font-size:11px;color:#64748B;margin-top:2px;">'
            f'Also covered by {htmlmod.escape(_also_text(also))}</div>'
        )
    summary_block = ""
    if llm_summary:
        summary_block = (
            f'<div style="margin-top:8px;font-size:13px;color:#CBD5E1;">'
            f'{htmlmod.escape(llm_summary)}</div>'
        )
    inner = (
        f'{importance_badge}{_ticker_badges(hit["tickers"])}'
        f'<div style="margin-top:6px;font-size:14px;font-weight:700;color:{COLOR_TEXT};">'
        f'<a href="{url}" style="color:#60A5FA;text-decoration:none;">{title}</a></div>'
        f'<div style="font-size:12px;color:#64748B;margin-top:3px;">{source}</div>'
        f'{also_block}'
        f'{summary_block}'
    )
    return _box(inner, COLOR_PANEL) + _gap(14)


def _section_html(title: str, color: str, hits_html: str) -> str:
    if not hits_html:
        return ""
    header = (
        f'<div style="color:#0B1220;font-weight:800;letter-spacing:0.6px;">{title}</div>'
    )
    # Spacing mirrors the old collapsed CSS margins: 18px above each section
    # (supplied by whatever precedes it), and every section ends 18px clear
    # (14px after its last card + 4px here).
    return _box(header, color, pad="10px 12px") + _gap(10) + hits_html + _gap(4)


def _also_text(names: list[str]) -> str:
    if len(names) <= 3:
        return ", ".join(names)
    return f"{', '.join(names[:3])} and {len(names) - 3} other(s)"


def _rollup_text(rollup) -> list[str]:
    out = []
    for pub, counts in rollup:
        out.append(f"{pub}: " + ", ".join(f"{t} ({n})" for t, n in counts))
    return out


def _newsletter_html(entries: list[dict], status: tuple[str, str] | None) -> str:
    rows = ""
    if status and status[0] != "ok":
        msg = "Newsletter inbox not configured" if status[0] == "not_configured" else "Newsletter inbox read FAILED"
        rows += _box(
            f'<div style="color:#FFFFFF;font-size:13px;"><b>{msg}</b>: {htmlmod.escape(status[1])}</div>',
            "#7F1D1D", pad="10px",
        ) + _gap(10)
    for e in entries:
        items_html = ""
        for it in e.get("items", []):
            tick = _ticker_badges(it.get("tickers") or [])
            kind = "" if it.get("direct") else '<span style="color:#94A3B8;font-size:11px;"> (indirect)</span>'
            items_html += (
                f'<div style="margin-top:8px;color:{COLOR_TEXT};">{tick}<b>{htmlmod.escape(it.get("headline", ""))}</b>{kind}'
                f'<div style="font-size:13px;color:#CBD5E1;margin-top:2px;">{htmlmod.escape(it.get("why", ""))}</div></div>'
            )
        note = ""
        if e.get("status") in ("failed", "parse_error", "skipped"):
            note = (f'<div style="margin-top:6px;font-size:12px;color:#FCA5A5;">'
                    f'Read {htmlmod.escape(e["status"])}: {htmlmod.escape(e.get("error", ""))}</div>')
        elif e.get("status") == "ok" and not e.get("items"):
            note = '<div style="margin-top:6px;font-size:12px;color:#94A3B8;">Nothing relevant to the portfolio.</div>'
        summary = (f'<div style="margin-top:6px;font-size:13px;color:#CBD5E1;">{htmlmod.escape(e["summary"])}</div>'
                   if e.get("summary") else "")
        rows += _box(
            f'<div style="font-size:12px;color:#A78BFA;font-weight:700;">{htmlmod.escape(e["label"])}</div>'
            f'<div style="margin-top:4px;font-size:14px;font-weight:700;color:{COLOR_TEXT};">'
            f'<a href="{htmlmod.escape(e["url"])}" style="color:#60A5FA;text-decoration:none;">'
            f'{htmlmod.escape(e["subject"])}</a></div>'
            f'{summary}{items_html}{note}',
            COLOR_PANEL,
        ) + _gap(14)
    return rows


def build_email(
    youtube_hits: list[dict],
    news_hits: list[dict],
    summaries: dict[str, str],   # seen_key → LLM summary
    lookback_hours: int,
    run_date: str,
    newsletters: list[dict] | None = None,
    newsletter_status: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Returns (plain_text, html).

    Tier-3 (low-quality rewrite) news hits are not listed individually: they
    collapse into one line per publisher at the bottom.
    """
    newsletters = newsletters or []
    rollup = low_quality_rollup(news_hits)
    low_hits = [h for h in news_hits if h.get("tier") == LOW_QUALITY_TIER]
    news_hits = [h for h in news_hits if h.get("tier") != LOW_QUALITY_TIER]

    # --- Plain text ---
    lines = ["Ned the News Agent", "=" * 18,
             f"Media Digest — last {lookback_hours}h — {run_date} (SGT)", ""]

    if youtube_hits:
        lines += ["YOUTUBE MENTIONS", "-" * 60]
        for h in youtube_hits:
            tickers = ", ".join(h["tickers"])
            importance = h.get("importance_level", "")
            importance_str = f"[{importance}] " if importance else ""
            lines.append(f"{importance_str}[{tickers}] {h['title']}")
            lines.append(f"  Source: {h['source']}  {h['url']}")
            if h["seen_key"] in summaries:
                lines.append(f"  {summaries[h['seen_key']]}")
            lines.append("")

    if news_hits:
        lines += ["NEWS & PRESS RELEASES", "-" * 60]
        for h in news_hits:
            tickers = ", ".join(h["tickers"])
            importance = h.get("importance_level", "")
            importance_str = f"[{importance}] " if importance else ""
            lines.append(f"{importance_str}[{tickers}] {h['title']}")
            lines.append(f"  Source: {h['source']}  {h['url']}")
            if h.get("also_covered_by"):
                lines.append(f"  Also covered by {_also_text(h['also_covered_by'])}")
            if h["seen_key"] in summaries:
                lines.append(f"  {summaries[h['seen_key']]}")
            lines.append("")

    if newsletters or (newsletter_status and newsletter_status[0] != "ok"):
        lines += ["NEWSLETTERS", "-" * 60]
        if newsletter_status and newsletter_status[0] != "ok":
            lines.append(f"Newsletter inbox {newsletter_status[0].upper()}: {newsletter_status[1]}")
        for e in newsletters:
            lines.append(f"{e['label']}: {e['subject']}")
            if e.get("summary"):
                lines.append(f"  {e['summary']}")
            for it in e.get("items", []):
                tag = "" if it.get("direct") else " (indirect)"
                lines.append(f"  [{', '.join(it.get('tickers') or [])}] {it.get('headline', '')}{tag}")
                lines.append(f"    {it.get('why', '')}")
            if e.get("status") in ("failed", "parse_error", "skipped"):
                lines.append(f"  Read {e['status']}: {e.get('error', '')}")
            lines.append(f"  {e['url']}")
            lines.append("")

    if rollup:
        lines += ["WIRE REWRITES (low-quality sources, not scored)", "-" * 60]
        lines += _rollup_text(rollup)
        for h in low_hits:
            lines.append(f"  [{', '.join(h['tickers'])}] {h['title']}  {h['url']}")
        lines.append("")

    if not youtube_hits and not news_hits and not newsletters:
        lines.append("No mentions found in the monitored channels and feeds this run.")

    plain = "\n".join(lines)

    # --- HTML ---
    yt_html = "".join(
        _hit_html(h, summaries.get(h["seen_key"])) for h in youtube_hits
    )
    news_html = "".join(
        _hit_html(h, summaries.get(h["seen_key"])) for h in news_hits
    )

    body_html = (
        f'<div style="font-size:22px;font-weight:900;margin-bottom:6px;color:{COLOR_TEXT};">Ned the News Agent</div>'
        f'<div style="font-size:14px;color:#D2D4D9;">'
        f'Media Digest — last {lookback_hours}h — {htmlmod.escape(run_date)} (SGT)</div>'
        + _gap(18)
        + _section_html("YOUTUBE MENTIONS", COLOR_YOUTUBE, yt_html)
        + _section_html("NEWS &amp; PRESS RELEASES", COLOR_NEWS, news_html)
        + _section_html("NEWSLETTERS", COLOR_NEWSLETTER, _newsletter_html(newsletters, newsletter_status))
    )

    if rollup:
        links = " ".join(
            f'<a href="{htmlmod.escape(h["url"])}" style="color:#64748B;">'
            f'{htmlmod.escape(h["tickers"][0])}</a>'
            for h in low_hits
        )
        body_html += _box(
            f'<div style="font-size:12px;color:#94A3B8;">'
            f'<b>Wire rewrites</b> (low-quality sources, not scored): '
            + htmlmod.escape("; ".join(_rollup_text(rollup)))
            + f'<div style="margin-top:4px;">{links}</div></div>',
            COLOR_BG, pad="10px 12px", extra_style="border:1px solid #334155;",
        ) + _gap(18)

    if not youtube_hits and not news_hits and not newsletters:
        body_html += _box(
            '<div style="color:#0B1220;font-weight:800;">No mentions found this run.</div>',
            COLOR_SILENCE,
        ) + _gap(18)

    # One full-width dark table carries the page background, so no white
    # shows around or between the cards on any client.
    body_html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{COLOR_BG}" style="width:100%;background-color:{COLOR_BG};">'
        f'<tr><td bgcolor="{COLOR_BG}" style="background-color:{COLOR_BG};padding:18px;'
        f'color:{COLOR_TEXT};font-family:{FONT_STACK};">'
        f'{body_html}</td></tr></table>'
    )
    return plain, body_html
