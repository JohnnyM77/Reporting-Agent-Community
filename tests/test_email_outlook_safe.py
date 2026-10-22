"""shared/email_html.outlook_safe: dark boxes render solid in desktop Outlook."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.email_html import outlook_safe
from shared.email_service import build_message


def _div_backgrounds(html: str) -> list[str]:
    out = []
    for m in re.finditer(r"<div\b[^>]*style=[\"']([^\"']*)[\"']", html):
        st = m.group(1).replace(" ", "").lower()
        if re.search(r"background(-color)?:(?!none|transparent)", st) and "display:inline" not in st:
            out.append(st)
    return out


def test_background_div_becomes_solid_table_cell():
    html = '<div style="margin:18px 0;padding:12px;background:#1E293B;border-radius:10px;">Hi</div>'
    out = outlook_safe(html)
    assert _div_backgrounds(out) == []
    assert 'bgcolor="#1E293B"' in out
    assert '<div style="margin:18px 0;">' in out              # spacing stays on a plain wrapper
    assert re.search(r'<td bgcolor="#1E293B" style="[^"]*padding:12px', out)
    assert out.count("<table") == out.count("</table>") == 1
    assert "Hi" in out


def test_spaces_and_single_quotes_in_styles():
    out = outlook_safe("<div style='padding:18px; background: #0B1220; color:#E5E7EB;'>x</div>")
    assert 'bgcolor="#0B1220"' in out and _div_backgrounds(out) == []


def test_inline_badges_and_plain_divs_untouched():
    html = ('<div style="margin-top:6px;">plain</div>'
            '<div style="display:inline-block;background:#DC2626;">CRITICAL</div>'
            '<span style="background:#334155">NHC</span>')
    assert outlook_safe(html) == html


def test_nested_and_idempotent():
    html = ('<div style="padding:18px;background:#0B1220;color:#E5E7EB;font-family:Arial;">'
            '<div style="font-size:22px;">Title</div>'
            '<div style="padding:12px;background:#1E293B;">card <div>inner</div></div>'
            '</div>')
    once = outlook_safe(html)
    assert outlook_safe(once) == once
    assert _div_backgrounds(once) == []
    assert once.count("<table") == once.count("</table>") == 2
    # The inner card cell carries the text styles it used to inherit
    inner = re.findall(r'<td bgcolor="#1E293B" style="([^"]*)"', once)[0]
    assert "color:#E5E7EB" in inner and "font-family:Arial" in inner


def test_inherits_text_styles_from_table_cells():
    html = ('<table><tr><td style="line-height:1.6;font-size:15px;">'
            '<div style="padding:6px;background:#f4f1ea;">stress</div></td></tr></table>')
    cell = re.findall(r'<td bgcolor="#f4f1ea" style="([^"]*)"', outlook_safe(html))[0]
    assert "line-height:1.6" in cell and "font-size:15px" in cell


def test_no_div_and_none_pass_through():
    assert outlook_safe(None) is None
    assert outlook_safe("<table><tr><td>x</td></tr></table>") == "<table><tr><td>x</td></tr></table>"


def test_every_email_is_converted_on_the_way_out():
    html = '<div style="padding:18px;background:#0B1220;color:#fff;">Bob</div>'
    msg = build_message(email_from="a@b.c", email_to="d@e.f", subject="s",
                        body_text="t", body_html=html)
    sent = msg.get_body(("html",)).get_content()
    assert 'bgcolor="#0B1220"' in sent and _div_backgrounds(sent) == []


def test_bob_digest_converts_cleanly():
    import agent
    _, html = agent.build_email([], ["MSV: 2026 AGM - CEO presentation"], ["WDS: Third Quarter 2026 Report"])
    assert _div_backgrounds(html)          # Bob still builds divs...
    assert _div_backgrounds(outlook_safe(html)) == []   # ...the sender fixes them
