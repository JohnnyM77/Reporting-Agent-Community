# shared/email_html.py
#
# Make an agent's email HTML render solid in desktop Outlook without changing
# how it looks anywhere else.
#
# Desktop Outlook (and Outlook.com in some views) uses Word's rendering
# engine, which only half-paints a <div>'s background: each line of text gets
# its own coloured strip and the white page shows between them. On a dark
# email that reads as a stack of black bars on white (Bob, 2026-10-21). Phone
# clients paint the same <div> solid, which is why the iPhone view was fine.
#
# Table cells are painted solid by every client. `outlook_safe()` rewrites
# every block-level <div> that carries a background into a one-cell table:
#
#     <div style="margin:18px 0;padding:12px;background:#1E293B;...">
#   becomes
#     <div style="margin:18px 0;"><table role="presentation" width="100%"
#       bgcolor="#1E293B" style="width:100%;border-collapse:separate;...">
#       <tr><td bgcolor="#1E293B" style="padding:12px;background:#1E293B;...">
#
# Margins and width stay on a plain wrapper <div> with no background (so
# spacing behaves exactly as before); the table is 100% of that wrapper and
# the cell keeps everything else (padding, colours, fonts, borders, radius). Text styles the div would have
# inherited from its ancestors are copied onto the cell too, because emails
# render in quirks mode where tables do not inherit fonts. Tables keep the
# same block box and margin collapsing as the div, so phone and webmail
# layouts are unchanged (checked by screenshot against the old output).
#
# It runs once, in shared/email_service.build_message, so every agent's email
# gets it. Inline elements (badge <span>s, inline-block divs) are left alone:
# Outlook paints those fine and a table would break their layout. Already
# table-built emails (Ned, Slinger's cards) pass through unchanged.

from __future__ import annotations

import re

# div is the only tag converted; the others are tracked so a converted cell
# can copy the text styles it would have inherited from them.
_TAG = re.compile(r"<(/?)(div|td|th|table|p|li|blockquote|center|body)\b([^>]*)>", re.I)
_STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*("([^"]*)"|'([^']*)')""", re.I | re.S)
_COLOUR = re.compile(
    r"(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?!none\b|transparent\b|inherit\b|initial\b|url\b)[a-zA-Z]+\b)"
)

# Text properties that inherit, so a converted cell keeps the look it had.
_INHERITED = (
    "color", "font-family", "font-size", "font-weight", "font-style",
    "line-height", "letter-spacing", "text-align", "text-transform",
    "white-space", "word-break", "overflow-wrap",
)
_WRAPPER_PROPS = ("margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
                  "width", "max-width", "min-width")


def _parse_style(style: str) -> list[tuple[str, str]]:
    out = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k:
            out.append((k, v))
    return out


def _style_str(decls: list[tuple[str, str]]) -> str:
    return ";".join(f"{k}:{v}" for k, v in decls) + (";" if decls else "")


def _background_colour(decls: list[tuple[str, str]]) -> str | None:
    """Colour of a background declaration, or None when there is no solid one."""
    value = None
    for k, v in decls:
        if k in ("background", "background-color"):
            value = v
    if not value:
        return None
    low = value.lower()
    if low in ("none", "transparent", "inherit", "initial", "unset"):
        return None
    m = _COLOUR.search(value)
    return m.group(1) if m else None


def _is_block(decls: list[tuple[str, str]]) -> bool:
    for k, v in decls:
        if k == "display" and v.lower() not in ("block", ""):
            return False
        if k in ("float", "position") and v.lower() not in ("none", "static", "relative"):
            return False
    return True


def outlook_safe(html: str | None) -> str | None:
    """Return *html* with every background-carrying block <div> turned into a
    one-cell table. Safe to call twice; returns the input unchanged when there
    is nothing to convert."""
    if not html or "<div" not in html.lower():
        return html

    out: list[str] = []
    # Stack of (tag, converted, inherited-text-props-for-children)
    stack: list[tuple[str, object, dict[str, str]]] = []
    pos = 0
    for m in _TAG.finditer(html):
        out.append(html[pos:m.start()])
        pos = m.end()
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        inherited = stack[-1][2] if stack else {}

        if closing:
            # Pop back to the matching open tag (tolerates sloppy nesting).
            idx = next((i for i in range(len(stack) - 1, -1, -1) if stack[i][0] == tag), None)
            if idx is None:
                out.append(m.group(0))
                continue
            converted = stack[idx][1]
            del stack[idx:]
            if converted:
                out.append("</div></td></tr></table>" + ("</div>" if converted == "wrapped" else ""))
            else:
                out.append(m.group(0))
            continue

        if attrs.rstrip().endswith("/"):   # <div/> — nothing to wrap
            out.append(m.group(0))
            continue

        sm = _STYLE_ATTR.search(attrs)
        style = (sm.group(2) if sm and sm.group(2) is not None else (sm.group(3) if sm else "")) or ""
        decls = _parse_style(style)

        child_inherited = dict(inherited)
        for k, v in decls:
            if k in _INHERITED:
                child_inherited[k] = v

        colour = _background_colour(decls) if tag == "div" else None
        if colour is None or not _is_block(decls):
            stack.append((tag, False, child_inherited))
            out.append(m.group(0))
            continue

        # Spacing and width stay on a plain (background-free) <div> wrapper,
        # so margins collapse and quirks-mode table-cell margin rules apply
        # exactly as they did to the original div. Only the painting moves
        # into the table.
        wrap_decls = [(k, v) for k, v in decls if k in _WRAPPER_PROPS]
        radius = [(k, v) for k, v in decls if k == "border-radius"]
        cell_decls = [(k, v) for k, v in decls if k not in _WRAPPER_PROPS and k != "display"]
        own = {k for k, _ in cell_decls}
        for k, v in inherited.items():
            if k not in own:
                cell_decls.append((k, v))
        table_decls = [("width", "100%")] + radius + [
            ("border-collapse", "separate"), ("background-color", colour)]

        other_attrs = _STYLE_ATTR.sub("", attrs).strip()
        other_attrs = f" {other_attrs}" if other_attrs else ""
        bg_attr = f' bgcolor="{colour}"' if colour.startswith("#") or colour.isalpha() else ""

        opener = f'<div style="{_style_str(wrap_decls)}">' if wrap_decls else ""
        out.append(
            f'{opener}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            f'{bg_attr} style="{_style_str(table_decls)}">'
            f'<tr><td{bg_attr}{other_attrs} style="{_style_str(cell_decls)}">'
            # Quirks mode drops the first/last child's margins inside a table
            # cell (a <p>'s bottom margin, say), which a padded <div> kept.
            # A flow-root block keeps them, so phones lay it out exactly as
            # before; Outlook ignores the property and is unaffected.
            '<div style="display:flow-root;">'
        )
        stack.append((tag, "wrapped" if wrap_decls else True, child_inherited))

    out.append(html[pos:])
    return "".join(out)
