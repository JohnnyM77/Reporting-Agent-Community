"""One PDF for the whole Sally run: a cover table, then per company the value
wedge chart and the memo.

Built with matplotlib (already installed for the wedge chart) from files the
run has written: wedge_chart.png, ranges_52w.png and memo.md in each ticker
folder. No HTML-to-PDF engine, so it renders the same on every runner.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#8a8985"
NAVY = "#1F2D4E"
ZONE_COLOURS = {"Above SELL": "#c0392b", "Upper third of wedge": "#f5b041", "Middle of wedge": "#5d8fc9",
                "Lower third of wedge": "#2e9e5b", "Below BUY": "#1a7f37"}

PAGE = (11.69, 8.27)          # A4 landscape, inches
WRAP = 135                    # characters per text line at 9pt
LINES_PER_PAGE = 46


def _clean(line: str) -> str:
    line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
    line = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", line)
    return line.replace("`", "")


def _memo_lines(md: str) -> list[tuple[str, str]]:
    """(style, text) per printed line: h1 / h2 / body / bullet / blank."""
    out: list[tuple[str, str]] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if out and out[-1][0] != "blank":
                out.append(("blank", ""))
            continue
        if line.startswith("# "):
            out.append(("h1", _clean(line[2:])))
            continue
        if line.startswith("#"):
            out.append(("h2", _clean(line.lstrip("#").strip())))
            continue
        bullet = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if bullet:
            mark = "-" if bullet.group(2) in "-*" else bullet.group(2)
            wrapped = textwrap.wrap(_clean(bullet.group(3)), WRAP - 4) or [""]
            out.append(("bullet", f"{mark} {wrapped[0]}"))
            out += [("bullet", f"  {w}") for w in wrapped[1:]]
            continue
        for w in textwrap.wrap(_clean(line), WRAP) or [""]:
            out.append(("body", w))
    return out


def _text_pages(pdf, title: str, lines: list[tuple[str, str]], plt) -> None:
    style = {"h1": (12, "bold", INK), "h2": (10, "bold", NAVY), "body": (8.6, "normal", INK),
             "bullet": (8.6, "normal", INK), "blank": (6, "normal", INK)}
    step = {"h1": 1.6, "h2": 1.35, "body": 1.0, "bullet": 1.0, "blank": 0.6}
    pages, cur, used = [], [], 0.0
    for kind, text in lines:
        if used + step[kind] > LINES_PER_PAGE and cur:
            pages.append(cur)
            cur, used = [], 0.0
        cur.append((kind, text))
        used += step[kind]
    if cur:
        pages.append(cur)
    for n, page in enumerate(pages, 1):
        fig = plt.figure(figsize=PAGE)
        fig.text(0.04, 0.965, title + (f"  (continued {n}/{len(pages)})" if n > 1 else ""),
                 fontsize=9, color=MUTED, va="top")
        y = 0.93
        for kind, text in page:
            size, weight, colour = style[kind]
            if text:
                fig.text(0.04, y, text, fontsize=size, fontweight=weight, color=colour, va="top",
                         family="DejaVu Sans", parse_math=False)
            y -= step[kind] * 0.0195
        pdf.savefig(fig)
        plt.close(fig)


def _image_page(pdf, title: str, png: Path, plt, note: str = "", box=(0.02, 0.02, 0.96, 0.89)) -> None:
    import matplotlib.image as mpimg
    img = mpimg.imread(str(png))
    fig = plt.figure(figsize=PAGE)
    fig.text(0.04, 0.975, title, fontsize=12, fontweight="bold", color=INK, va="top")
    if note:
        fig.text(0.04, 0.945, note, fontsize=8.5, color=INK_2, va="top", parse_math=False)
    ax = fig.add_axes(list(box))
    ax.imshow(img)
    ax.axis("off")
    pdf.savefig(fig, dpi=200)
    plt.close(fig)


def _cover(pdf, title: str, subtitle: str, rows: list[dict], plt) -> None:
    fig = plt.figure(figsize=PAGE)
    fig.text(0.04, 0.95, title, fontsize=18, fontweight="bold", color=INK, va="top")
    fig.text(0.04, 0.905, subtitle, fontsize=10, color=INK_2, va="top", parse_math=False)
    cols = ["Ticker", "Alert tier", "Below 52w high", "Value wedge", "BUY / fair / SELL", "Verdict"]
    body = []
    colours = []
    for r in rows:
        pos = r.get("wedge_position")
        zone = r.get("wedge_zone")
        bfs = "n/a"
        if r.get("wedge_buy_value") is not None:
            fair = r.get("wedge_fair_value")
            bfs = (f"${r['wedge_buy_value']:,.2f} / " + (f"${fair:,.2f}" if fair else "-")
                   + f" / ${r['wedge_sell_value']:,.2f}")
        body.append([r.get("ticker", ""), str(r.get("alert_tier", "")),
                     f"{r.get('distance_to_high_pct', 'n/a')}%",
                     f"{zone} ({pos:.0%})" if pos is not None else (r.get("wedge_missing") or "no wedge"),
                     bfs, str(r.get("sally_verdict", ""))])
        colours.append(ZONE_COLOURS.get(zone or "", "#ffffff"))
    ax = fig.add_axes([0.04, 0.08, 0.92, 0.78])
    ax.axis("off")
    if body:
        tbl = ax.table(cellText=body, colLabels=cols, loc="upper left", cellLoc="left",
                       colWidths=[0.08, 0.17, 0.11, 0.24, 0.18, 0.22])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.6)
        for (i, j), cell in tbl.get_celld().items():
            cell.set_edgecolor("#d9d8d3")
            if i == 0:
                cell.set_facecolor(NAVY)
                cell.get_text().set_color("white")
                cell.get_text().set_fontweight("bold")
            elif j == 3 and colours[i - 1] != "#ffffff":
                cell.get_text().set_color(colours[i - 1])
                cell.get_text().set_fontweight("bold")
    else:
        ax.text(0, 0.9, "Nothing flagged this week.", fontsize=11, color=INK_2)
    fig.text(0.04, 0.04, "Value wedge: BUY = EPS x BUY P/E, SELL = EPS x SELL P/E, fair 30% of the way up "
             "unless the valuation file says otherwise. Forecasts are analyst consensus or stated assumptions, "
             "never reported figures.", fontsize=7.5, color=MUTED, parse_math=False)
    pdf.savefig(fig)
    plt.close(fig)


def build_report_pdf(rows: list[dict], run_folder: Path, out_path: Path, title: str, subtitle: str) -> Path | None:
    """rows = the run's flagged summaries (ticker, alert_tier, wedge_* fields)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        print("[sally] matplotlib missing: no PDF report")
        return None
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(out_path) as pdf:
        _cover(pdf, title, subtitle, rows, plt)
        for r in rows:
            t = r["ticker"]
            folder = Path(run_folder) / t
            name = f"{r.get('company_name') or t} ({t})"
            png = folder / "wedge_chart.png"
            if png.exists():
                _image_page(pdf, f"{name}: the value wedge", png, plt, note=r.get("wedge_low_line") or "")
            ranges = folder / "ranges_52w.png"
            if ranges.exists():
                _image_page(pdf, f"{name}: 52-week P/E and P/FCF", ranges, plt, box=(0.15, 0.30, 0.70, 0.60),
                            note="Statutory, trailing 12 months, from EODHD statements; each result counts "
                                 "from its release date.")
            memo = folder / "memo.md"
            if memo.exists():
                _text_pages(pdf, name, _memo_lines(memo.read_text(encoding="utf-8")), plt)
        info = pdf.infodict()
        info["Title"] = title
        info["Author"] = "Selling Sally"
    return out_path
