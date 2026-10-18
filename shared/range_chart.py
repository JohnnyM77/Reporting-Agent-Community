"""Small inline PNG of a stock's 52-week P/E and P/FCF, for agent emails.

Two panels side by side, one line each (never a dual axis: the two
multiples live on different scales). Each panel shows the daily multiple
over the last 52 weeks, the 52-week low and high as faint reference lines,
and the current value as a dot with its label. Gaps are real gaps (a loss,
negative FCF, an unusable share count), not interpolated.

Rendered at 2x so it stays sharp on a phone; the email shows it at
``DISPLAY_WIDTH`` px. Data comes from ``shared.ranges.range_payload``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

DISPLAY_WIDTH = 560

INK = "#111827"        # values and titles
MUTED = "#6b7280"      # axis text, notes
GRID = "#e5e7eb"
LINE = "#1f4e79"       # the one series colour (navy)
BAND = "#eef2f7"


def _fmt(v: float) -> str:
    return f"{v:.1f}x" if abs(v) < 100 else f"{v:.0f}x"


def _label_gaps(ax, x, gaps: list, neg_word: str) -> None:
    """Write why a stretch has no line, in muted ink, centred in the stretch."""
    runs, start = [], None
    for i, g in enumerate(list(gaps) + [None]):
        if g and start is None:
            start = i
        elif not g and start is not None:
            runs.append((start, i - 1, gaps[start]))
            start = None
    for a, b, kind in runs:
        if b - a + 1 < max(8, len(gaps) // 8):     # too short to label
            continue
        mid = x[a] + (x[b] - x[a]) / 2
        ax.text(mid, 0.5, f"n/m: {neg_word}" if kind == "neg" else "no data",
                transform=ax.get_xaxis_transform(), ha="center", va="center", fontsize=7, color=MUTED,
                zorder=5, bbox={"boxstyle": "square,pad=0.25", "fc": BAND, "ec": "none"})


def render_range_chart(ranges: dict | None, output_path: str | Path, ticker: str = "") -> Optional[Path]:
    """Write the PNG and return its path, or None when there is nothing to plot.

    Never raises: a missing library or bad data logs and returns None, and the
    email simply carries no chart for that ticker.
    """
    if not ranges:
        return None
    series = ranges.get("series") or {}
    dates = series.get("dates") or []
    panels = [(k, t) for k, t in (("pe", "P/E"), ("pfcf", "P/FCF"))
              if any(v is not None for v in (series.get(k) or []))]
    if not dates or not panels:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        import pandas as pd

        x = pd.to_datetime(dates)
        fig, axes = plt.subplots(1, 2, figsize=(5.6, 1.6), dpi=200)
        fig.patch.set_facecolor("white")
        for ax, (key, title) in zip(axes, panels + [(None, None)] * (2 - len(panels))):
            if key is None:
                ax.axis("off")
                ax.text(0.5, 0.5, "P/FCF n/a", transform=ax.transAxes, ha="center", va="center",
                        fontsize=7, color=MUTED)
                continue
            y = pd.Series(series[key], index=x, dtype=float)
            r = ranges.get(key) or {}
            lo, hi = y.min(), y.max()
            pad = (hi - lo) * 0.18 or abs(hi) * 0.05 or 1.0
            ax.set_ylim(lo - pad, hi + pad * 1.6)
            ax.axhspan(lo, hi, color=BAND, zorder=0, lw=0)
            for level in (lo, hi):
                ax.axhline(level, color=GRID, lw=0.6, zorder=1)
            for rel in series.get("results") or []:
                ax.axvline(pd.Timestamp(rel), color=MUTED, lw=0.5, ls=(0, (1, 2)), zorder=2)
            ax.plot(x, y.values, color=LINE, lw=1.1, zorder=3, solid_capstyle="round")
            _label_gaps(ax, x, series.get(f"{key}_gap") or [], "loss" if key == "pe" else "negative FCF")
            last = y.dropna()
            if len(last):
                ax.scatter([last.index[-1]], [last.iloc[-1]], s=10, color=LINE, zorder=4,
                           edgecolors="white", linewidths=0.6)
            # low / high labels at the right edge, in muted ink
            ax.annotate(f"high {_fmt(hi)}", xy=(1, hi), xycoords=("axes fraction", "data"),
                        xytext=(2, 0), textcoords="offset points", fontsize=6.5, color=MUTED, va="center")
            ax.annotate(f"low {_fmt(lo)}", xy=(1, lo), xycoords=("axes fraction", "data"),
                        xytext=(2, 0), textcoords="offset points", fontsize=6.5, color=MUTED, va="center")
            cur = r.get("current")
            pos = r.get("position")
            head = f"{title} (TTM)  {_fmt(cur)}" if cur is not None else f"{title} (TTM)  n/m today"
            ax.set_title(head, loc="left", fontsize=8, color=INK, fontweight="bold", pad=3)
            if pos is not None:
                ax.set_title(f"{pos:.0%} of range", loc="right", fontsize=7, color=MUTED, pad=3)
            ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
            ax.tick_params(axis="both", labelsize=6.5, colors=MUTED, length=0, pad=1.5)
            ax.set_yticks([])
            for side in ("top", "right", "left"):
                ax.spines[side].set_visible(False)
            ax.spines["bottom"].set_color(GRID)
            ax.set_xlim(x.min(), x.max())
        fig.subplots_adjust(left=0.01, right=0.86, top=0.80, bottom=0.17, wspace=0.32)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out, dpi=200, facecolor="white")
        plt.close(fig)
        return out
    except Exception as exc:  # never let a chart break an email
        print(f"[range_chart] {ticker} chart failed: {type(exc).__name__}: {exc}", flush=True)
        return None


def range_chart_html(cid: str, ticker: str, ranges: dict | None) -> str:
    """Email-safe block: small heading, the inline image, one muted basis line."""
    notes = "; ".join(((ranges or {}).get("notes") or [])[:2])   # the email gets a line, not a log
    basis = (ranges or {}).get("basis", "")
    return (
        "<table role='presentation' cellpadding='0' cellspacing='0' border='0' "
        f"style='width:{DISPLAY_WIDTH}px;max-width:100%;border-collapse:collapse;margin:14px 0 4px 0;"
        "font-family:Arial,Helvetica,sans-serif'>"
        f"<tr><td style='padding:0 0 4px 0;font-size:12px;color:{INK}'><b>{ticker}</b>"
        f" <span style='color:{MUTED}'>52-week valuation</span></td></tr>"
        f"<tr><td style='padding:0'><img src='cid:{cid}' width='{DISPLAY_WIDTH}' alt='{ticker} 52-week P/E and P/FCF' "
        "style='display:block;width:100%;max-width:560px;height:auto;border:0'></td></tr>"
        f"<tr><td style='padding:3px 0 0 0;font-size:10px;color:{MUTED}'>{basis} Dotted lines: results released."
        + (f" {notes}." if notes else "") + "</td></tr></table>"
    )
