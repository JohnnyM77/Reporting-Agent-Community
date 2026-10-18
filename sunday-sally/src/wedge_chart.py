"""Render a WedgeResult as a four-panel PNG.

1. Price vs the BUY/SELL corridor (the shaded wedge is the main element).
2. Actual PE vs BUY PE / SELL PE: the multiple effect.
3. Absolute wedge ($ per share): moves with EPS.
4. Relative wedge (SELL PE / BUY PE - 1): moves only with the multiples.

Panels share the date axis; each has its own single y-axis. Numbered markers
on panel 1 key into the "why the corridor moved" list printed under the chart,
so the PNG explains itself when forwarded on its own.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from .value_wedge import WedgeResult

INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#8a8985"
GRID = "#e6e5e0"
PRICE = "#2a78d6"
BUY = "#008300"
SELL = "#e34948"
WEDGE = "#4a3aa7"
PE = "#eb6834"
EVENT_COL = {"earnings": INK_2, "multiple": WEDGE, "note": "#a0522d", "thesis": "#a0522d",
             "decision": BUY}

MAX_EVENTS = 22
CASE_COLOURS = ("#1a8f6e", "#8a5a9e", "#b8860b")   # forecast scenarios: recovery, no recovery, third


def _series(points, attr):
    return [getattr(p, attr) if getattr(p, attr) is not None else float("nan") for p in points]


def _pick_events(events):
    if len(events) <= MAX_EVENTS:
        return events
    keep = [e for e in events if e.kind != "earnings"]
    rest = [e for e in events if e.kind == "earnings"]
    room = max(0, MAX_EVENTS - len(keep))
    return sorted(keep[:MAX_EVENTS] + rest[-room:] if room else keep[:MAX_EVENTS], key=lambda e: e.date)


def render_wedge_chart(result: WedgeResult, output_path: str | Path) -> Path | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        from matplotlib.transforms import blended_transform_factory, offset_copy
    except ImportError:
        print("[wedge] matplotlib not installed; no chart")
        return None

    pts = [p for p in result.points]
    if not pts:
        return None
    inp = result.inputs
    cur = result.current
    import numpy as np
    import pandas as pd
    from .value_wedge import daily_corridor, forecast_corridor

    day = daily_corridor(result)
    fc = forecast_corridor(result)
    fcd = fc.index.to_pydatetime() if not fc.empty else None
    cases = [c["label"] for c in inp.forecast_cases] or [None]
    case_fc = {c: forecast_corridor(result, c) for c in cases} if fcd is not None else {}
    dd = day.index.to_pydatetime()
    price = day["price"].to_numpy(float)
    buy = day["buy"].to_numpy(float)
    sell = day["sell"].to_numpy(float)
    ape = day["pe"].to_numpy(float)
    bpe = day["buy_pe"].to_numpy(float)
    spe = day["sell_pe"].to_numpy(float)
    fair = day["fair"].to_numpy(float)
    fpe = day["fair_pe"].to_numpy(float)
    smoothed = bool(inp.smoothing)
    buy_rep = day["buy_reported"].to_numpy(float)
    sell_rep = day["sell_reported"].to_numpy(float)
    pe_rep = day["pe_reported"].to_numpy(float)

    events = _pick_events(result.events)
    n_lines = sum(len(textwrap.wrap(e.text, 150)) for e in events) + len(inp.warnings) + 3

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK_2,
                         "xtick.color": INK_2, "ytick.color": INK_2})
    notes_h = 0.18 * n_lines + 0.4
    fig_h = 10.2 + notes_h
    fig = plt.figure(figsize=(13, fig_h))
    gs = fig.add_gridspec(3, 1, height_ratios=[6.0, 2.4, notes_h], hspace=0.17,
                          top=1 - 1.40 / fig_h, bottom=0.01)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    axn = fig.add_subplot(gs[2])
    axn.axis("off")
    for ax in (ax1, ax2):
        ax.set_facecolor("white")
        ax.grid(True, axis="y", color=GRID, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)

    # ── Panel 1: daily price vs the BUY/SELL corridor ──────────────────────
    ok = ~np.isnan(buy) & ~np.isnan(sell)
    ax1.fill_between(dd, buy, sell, where=ok, color="#ecebe6", linewidth=0, step="post",
                     label=f"Wedge: BUY to SELL")
    ax1.fill_between(dd, price, buy, where=ok & (price < buy), color=BUY, alpha=0.30, linewidth=0,
                     interpolate=True, label="Price below BUY: buying zone")
    ax1.fill_between(dd, sell, price, where=ok & (price > sell), color=SELL, alpha=0.28, linewidth=0,
                     interpolate=True, label="Price above SELL: selling zone")
    eps_word = "smoothed EPS" if smoothed else "EPS"
    bl = f"BUY = {eps_word} x {cur.buy_pe:g}" if cur and cur.buy_pe else "BUY"
    sl = f"SELL = {eps_word} x {cur.sell_pe:g}" if cur and cur.sell_pe else "SELL"
    if smoothed:
        # Statutory corridor in the background: what reported EPS alone said.
        ax1.step(dd, buy_rep, where="post", color=BUY, linewidth=0.9, alpha=0.35, linestyle=(0, (4, 2)),
                 label="Statutory BUY / SELL (reported EPS), for reference")
        ax1.step(dd, sell_rep, where="post", color=SELL, linewidth=0.9, alpha=0.35, linestyle=(0, (4, 2)))
    ax1.step(dd, buy, where="post", color=BUY, linewidth=2.0, label=bl)
    ax1.step(dd, sell, where="post", color=SELL, linewidth=2.0, label=sl)
    if not np.isnan(fair).all():
        fp = np.nanmax(fpe)
        ax1.step(dd, fair, where="post", color=INK_2, linewidth=1.3, linestyle=(0, (6, 3)),
                 label=f"Fair value = {eps_word} x {fp:.1f} ({(inp.fair_split or 0):.0%} of the way BUY to SELL)")
    ax1.plot(dd, price, color=PRICE, linewidth=1.2, label="Share price (daily close)", zorder=4)

    # Where there is no corridor, say why instead of leaving a silent gap.
    def spans(test):
        out, s0, prev = [], None, None
        for d, e in zip(day.index, day["eps"]):
            hit = test(e)
            if hit and s0 is None:
                s0 = d
            if s0 is not None and not hit:
                out.append((s0, d))
                s0 = None
            prev = d
        if s0 is not None:
            out.append((s0, prev))
        return out
    for i, (a, b) in enumerate(spans(lambda e: e != e)):
        ax1.axvspan(a, b, facecolor="#f2f2f0", hatch="///", edgecolor="#c8c7c2", linewidth=0, zorder=0,
                    label="No EPS in the data" if i == 0 else None)
    for i, (a, b) in enumerate(spans(lambda e: e == e and e <= 0)):
        ax1.axvspan(a, b, facecolor="#f6e9e9", hatch="xx", edgecolor="#e2c4c4", linewidth=0, zorder=0,
                    label="Loss (EPS negative): no PE-based value" if i == 0 else None)
    if smoothed:
        rep_eps = day["eps_reported"]
        loss_spans = []
        s0 = None
        for d, v in zip(rep_eps.index, rep_eps):
            if v == v and v <= 0 and s0 is None:
                s0 = d
            elif s0 is not None and not (v == v and v <= 0):
                loss_spans.append((s0, d)); s0 = None
        if s0 is not None:
            loss_spans.append((s0, rep_eps.index[-1]))
        for i, (a, b) in enumerate(loss_spans):
            ax1.axvspan(a, b, facecolor="#f6e9e9", hatch="xx", edgecolor="#e2c4c4", linewidth=0, zorder=0,
                        label="Statutory loss: one-off, left out of the smoothing" if i == 0 else None)

    # Statutory EPS understating earning power (e.g. a factory move): amber
    # band, plus a faint reference corridor on the named normal year's EPS.
    for i, dpe in enumerate(inp.depressed or []):
        a0 = pd.Timestamp(dpe["start"])
        a1 = pd.Timestamp(dpe["end"]) if dpe.get("end") else day.index[-1]
        if a1 < day.index[0] or a0 > day.index[-1]:
            continue
        a0 = max(a0, day.index[0])
        ax1.axvspan(a0, a1, facecolor="#f5b041", alpha=0.10, linewidth=0, zorder=0,
                    label=f"{dpe['label']}: statutory EPS understates earning power" if i == 0 else None)
        ref = dpe.get("reference_eps")
        if ref and cur and cur.buy_pe and not inp.eps_currency:
            span_x = [a0, a1]
            refs = [(cur.buy_pe, BUY), (cur.sell_pe, SELL)]
            if cur.fair_pe:
                refs.append((cur.fair_pe, INK_2))
            for j, (pe_x, col) in enumerate(refs):
                v = ref * pe_x / 100
                ax1.plot(span_x, [v, v], color=col, linewidth=1.1, linestyle=(0, (1, 2)), alpha=0.8,
                         label=(f"Earning-power reference: {dpe['reference_period']} EPS {ref:.1f}c x BUY/fair/SELL"
                                if (i == 0 and j == 0) else None))

    buys = [e for e in result.events if e.kind == "decision" and e.text.startswith("Bought")]
    if buys:
        def price_on(d):
            s = day["price"][day.index >= pd.Timestamp(d)]
            return float(s.iloc[0]) if not s.empty else float(day["price"].iloc[-1])
        ax1.scatter([e.date for e in buys], [price_on(e.date) for e in buys], marker="^", s=110,
                    color=BUY, edgecolor="white", linewidth=1.4, zorder=7, label="Your buy (IRR ledger)")
    sells = [e for e in result.events if e.kind == "decision" and e.text.startswith("Sold")]
    if sells:
        def close_on(d):
            s = day["price"][day.index <= pd.Timestamp(d)]
            return float(s.iloc[-1]) if not s.empty else float(day["price"].iloc[0])
        ax1.scatter([e.date for e in sells], [close_on(e.date) for e in sells], marker="v", s=120,
                    color=SELL, edgecolor="white", linewidth=1.4, zorder=7, label="Your sale (IRR ledger)")
    for e in buys + sells:
        px = (close_on if e in sells else price_on)(e.date)
        ax1.annotate(f"{'Sold' if e in sells else 'Bought'} ${px:,.2f}", (e.date, px),
                     xytext=(0, -16 if e in buys else -20), textcoords="offset points", ha="center",
                     fontsize=7.5, fontweight="bold", color=BUY if e in buys else SELL, zorder=8,
                     parse_math=False)

    hi_d = [pt.date for pt in pts if pt.new_52w_high]
    hi_v = [pt.price for pt in pts if pt.new_52w_high]
    if hi_d:
        ax1.scatter(hi_d, [v * 1.04 for v in hi_v], marker="v", s=9, color=INK_2, zorder=5,
                    label="New 52-week high (review trigger, not a value)")

    # ── Forecast: right of today, lighter, never mistaken for history ─────
    # One case: the corridor continues in BUY green / SELL red, dashed.
    # Several cases (e.g. recovery vs no recovery): each gets its own band and
    # fair line in its own colour, so the two futures can be compared.
    if fcd is not None:
        today = dd[-1]
        xs = np.concatenate([[today], fcd])

        def ext(arr, first):
            return np.concatenate([[first], arr])
        ax1.axvspan(today, fcd[-1], facecolor="#f7f6fb", linewidth=0, zorder=0)
        many = len(case_fc) > 1
        for k, (case, cf) in enumerate(case_fc.items()):
            if cf.empty:
                continue
            f_buy, f_sell, f_fair = (cf[c].to_numpy(float) for c in ("buy", "sell", "fair"))
            name = f"{case or inp.forecast_label} (forecast, not reported)"
            if many:
                col = CASE_COLOURS[k % len(CASE_COLOURS)]
                ax1.fill_between(xs, ext(f_buy, buy[-1]), ext(f_sell, sell[-1]), step="post", color=col,
                                 alpha=0.13, linewidth=0, label=f"{name}: BUY to SELL")
                for arr, base in ((f_buy, buy[-1]), (f_sell, sell[-1])):
                    ax1.step(xs, ext(arr, base), where="post", color=col, linewidth=1.0, alpha=0.8)
                if not np.isnan(f_fair).all():
                    ax1.step(xs, ext(f_fair, fair[-1]), where="post", color=col, linewidth=1.8,
                             linestyle=(0, (6, 3)), label=f"{case}: fair value")
            else:
                ax1.fill_between(xs, ext(f_buy, buy[-1]), ext(f_sell, sell[-1]), step="post", color="#ecebe6",
                                 alpha=0.55, linewidth=0, hatch="..", edgecolor="#d5d3cc", label=name)
                ax1.step(xs, ext(f_buy, buy[-1]), where="post", color=BUY, linewidth=1.6, linestyle=(0, (5, 2)))
                ax1.step(xs, ext(f_sell, sell[-1]), where="post", color=SELL, linewidth=1.6, linestyle=(0, (5, 2)))
                if not np.isnan(f_fair).all():
                    ax1.step(xs, ext(f_fair, fair[-1]), where="post", color=INK_2, linewidth=1.1,
                             linestyle=(0, (6, 3)))
        ax1.plot([today, fcd[-1]], [price[-1], price[-1]], color=PRICE, linewidth=1.0, linestyle=(0, (1, 2)),
                 label="Today's price held flat across the forecast, for comparison")
        ax1.axvline(today, color=INK_2, linewidth=0.9, zorder=3)
        ax1.text(today, 0.985, " today | forecast ", transform=blended_transform_factory(ax1.transData, ax1.transAxes),
                 ha="left", va="top", fontsize=7.5, color=INK_2, fontstyle="italic")
        for r in result.forecast:
            rd = pd.Timestamp(r["date"]).to_pydatetime()
            if rd > fcd[-1]:
                continue
            k = cases.index(r.get("case")) if r.get("case") in cases else 0
            ax1.annotate(f"{r['period'].replace('FY20', 'FY')}F {r['eps_cents']:.0f}c", (rd, r["sell_value"]),
                         xytext=(-4, 4), textcoords="offset points", ha="right", fontsize=7.5,
                         color=CASE_COLOURS[k % len(CASE_COLOURS)] if many else INK_2, parse_math=False)
        cf0 = next(iter(case_fc.values()))
        ax2.fill_between(xs, ext(cf0["buy_pe"].to_numpy(float), bpe[-1]), ext(cf0["sell_pe"].to_numpy(float), spe[-1]),
                         step="post", color="#ecebe6", alpha=0.55, linewidth=0)
        ax2.step(xs, ext(cf0["buy_pe"].to_numpy(float), bpe[-1]), where="post", color=BUY, linewidth=1.2, linestyle="--")
        ax2.step(xs, ext(cf0["sell_pe"].to_numpy(float), spe[-1]), where="post", color=SELL, linewidth=1.2, linestyle="--")
        for k, case in enumerate(cases):
            fwd = [(pd.Timestamp(r["date"]).to_pydatetime(), r["forward_pe_today"]) for r in result.forecast
                   if r.get("forward_pe_today") and (r.get("case") == case or case is None)
                   and pd.Timestamp(r["date"]).to_pydatetime() <= fcd[-1]]
            if not fwd:
                continue
            col = CASE_COLOURS[k % len(CASE_COLOURS)] if many else PE
            ax2.scatter([a for a, _ in fwd], [b for _, b in fwd], marker="D", s=22, color=col, zorder=5,
                        label=f"Today's price / {case + ' ' if many else 'forecast '}EPS")
            for a, b in fwd:
                ax2.annotate(f"{b:.0f}x", (a, b), xytext=(5, 0), textcoords="offset points", va="center",
                             fontsize=7.5, color=col)
        ax2.axvline(today, color=INK_2, linewidth=0.9, zorder=3)

    vis = np.concatenate([price, sell[ok]]) if ok.any() else price
    for cf in case_fc.values():
        if not cf.empty:
            vis = np.concatenate([vis, cf["sell"].to_numpy(float)])
    top = float(np.nanmax(vis))
    ax1.set_ylim(0, top * 1.18)
    ax1.set_ylabel(f"Price per share ({inp.currency}$)")
    ax1.yaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.2f}"))

    trans = blended_transform_factory(ax1.transData, ax1.transAxes)
    for i, e in enumerate(events, 1):
        col = EVENT_COL.get(e.kind, INK_2)
        for ax in (ax1, ax2):
            ax.axvline(e.date, color=col, linewidth=0.6,
                       linestyle="--" if e.kind == "multiple" else ":", alpha=0.6, zorder=1)
        ax1.text(e.date, 1.015, str(i), transform=trans, ha="center", va="bottom", fontsize=7.5,
                 color="white", fontweight="bold", zorder=6, clip_on=False,
                 bbox=dict(boxstyle="circle,pad=0.25", facecolor=col, edgecolor="none"))

    # Direct labels at the right edge.
    if fcd is not None and len(case_fc) > 1:
        x_end = fcd[-1]
        labels = [(cur.price, f" Price today ${cur.price:,.2f}", PRICE)]
        for k, case in enumerate(cases):
            rows = [r for r in result.forecast if r.get("case") == case]
            if not rows:
                continue
            f = rows[-1]
            tag = f"{f['period'].replace('FY20', 'FY')}F"
            val = f.get("fair_value") or f["buy_value"]
            labels.append((val, f" {case} {tag}: fair ${val:,.2f}  (BUY ${f['buy_value']:,.2f} / "
                                f"SELL ${f['sell_value']:,.2f})", CASE_COLOURS[k % len(CASE_COLOURS)]))
    elif fcd is not None and result.forecast:
        f = result.forecast[-1]
        tag = f"{f['period'].replace('FY20', 'FY')}F"
        x_end = fcd[-1]
        labels = [
            (f["sell_value"], f" SELL {f['sell_pe']:g}x  ${f['sell_value']:,.2f} ({tag})", SELL),
            (f["buy_value"], f" BUY {f['buy_pe']:g}x  ${f['buy_value']:,.2f} ({tag})", BUY),
            (cur.price, f" Price today ${cur.price:,.2f}", PRICE),
        ]
        if f.get("fair_value"):
            labels.append((f["fair_value"], f" Fair {f['fair_pe']:.1f}x  ${f['fair_value']:,.2f} ({tag})", INK_2))
    elif cur and cur.buy_value is not None:
        x_end = dd[-1]
        labels = [
            (cur.sell_value, f" SELL {cur.sell_pe:g}x  ${cur.sell_value:,.2f}", SELL),
            (cur.buy_value, f" BUY {cur.buy_pe:g}x  ${cur.buy_value:,.2f}", BUY),
            (cur.price, f" Price ${cur.price:,.2f}", PRICE),
        ]
        if cur.fair_value:
            labels.append((cur.fair_value, f" Fair {cur.fair_pe:.1f}x  ${cur.fair_value:,.2f}", INK_2))
    else:
        labels = []
    if labels:
        labels.sort()
        gap = top * 1.18 * 0.045           # keep boxes from overlapping
        placed: list[float] = []
        for val, txt, col in labels:
            y = max(val, placed[-1] + gap) if placed else val
            placed.append(y)
            ax1.text(x_end, y, txt, transform=offset_copy(ax1.transData, fig=fig, x=5, units="points"),
                     va="center", clip_on=False, fontsize=8.5, color=INK, fontweight="bold", parse_math=False,
                     bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor=col, linewidth=1))
    ax1.legend(loc="upper left", fontsize=7.8, frameon=True, framealpha=0.95, edgecolor=GRID, ncol=2)

    # ── Panel 2: PE ────────────────────────────────────────────────────────
    ax2.fill_between(dd, bpe, spe, color="#ecebe6", linewidth=0, step="post")
    ax2.step(dd, bpe, where="post", color=BUY, linewidth=1.4, linestyle="--", label="BUY PE")
    ax2.step(dd, spe, where="post", color=SELL, linewidth=1.4, linestyle="--", label="SELL PE")
    if smoothed:
        ax2.plot(dd, pe_rep, color=PE, linewidth=0.8, alpha=0.3, label="PE on reported EPS (faint)")
    if not np.isnan(fpe).all():
        ax2.step(dd, fpe, where="post", color=INK_2, linewidth=1.0, linestyle=(0, (6, 3)), label="Fair PE")
    ax2.plot(dd, ape, color=PE, linewidth=1.2,
             label="Actual PE (price / smoothed EPS)" if smoothed else "Actual PE (price / EPS in force)")
    finite = ape[~np.isnan(ape)]
    smax = np.nanmax(spe) if not np.isnan(spe).all() else 30
    cap = max(smax * 2.2, np.percentile(finite, 90) * 1.1 if finite.size else 60)
    ax2.set_ylim(0, cap)
    if finite.size and finite.max() > cap:
        ax2.text(0.995, 0.97, f"actual PE peaks at {finite.max():.0f}x (clipped)", transform=ax2.transAxes,
                 ha="right", va="top", fontsize=7.5, color=INK_2)
    ax2.set_ylabel("PE (x)")
    ax2.legend(loc="upper left", fontsize=7.8, frameon=True, framealpha=0.95, edgecolor=GRID, ncol=5)

    # ── X axis: financial years ────────────────────────────────────────────
    # Label each financial year in the middle of its span (FY16 = Jul-2015 to
    # Jun-2016 for a June year end), faint line at each year start.
    import datetime as _dt
    fem = inp.fy_end_month or 12
    first = day.index[0].date()
    last = (fc.index[-1] if not fc.empty else day.index[-1]).date()
    today_d = day.index[-1].date()
    ticks, labels_fy = [], []
    for y in range(first.year - 1, last.year + 2):
        fy_end = _dt.date(y, fem, 1)
        fy_end = (pd.Timestamp(fy_end) + pd.offsets.MonthEnd(0)).date()
        fy_start = (pd.Timestamp(fy_end) - pd.DateOffset(years=1) + pd.Timedelta(days=1)).date()
        mid = fy_start + (fy_end - fy_start) / 2
        if first <= fy_start <= last:
            for ax in (ax1, ax2):
                ax.axvline(fy_start, color="#d9d8d3", linewidth=0.8, zorder=0)
        if first <= mid <= last:
            ticks.append(mid)
            labels_fy.append(f"FY{y % 100:02d}" + ("F" if fy_end > today_d else ""))
    # FY labels sit directly under the price chart (where the eye is) and
    # again under the PE panel; the axes share the ticks.
    ax2.set_xticks(ticks)
    ax2.set_xticklabels(labels_fy, fontsize=9, fontweight="bold", color=INK)
    ax1.tick_params(axis="x", labelbottom=True, length=0, pad=3)
    ax1.set_xticklabels(labels_fy, fontsize=9, fontweight="bold", color=INK)
    ax2.tick_params(axis="x", length=0, pad=3)
    ax2.set_xlim(dd[0], fcd[-1] if fcd is not None else dd[-1])
    ax2.set_xlabel(f"Financial year (ends {pd.Timestamp(2000, fem, 1):%B}); faint lines mark each year's start",
                   fontsize=8, color=MUTED)

    # ── Title + notes ──────────────────────────────────────────────────────
    t = inp.ticker.split(".")[0]
    y0 = 1 - 0.15 / fig_h
    fig.text(0.06, y0, f"{inp.company_name} ({t}): the wedge between BUY and SELL", ha="left", va="top",
             fontsize=14, fontweight="bold", color=INK)
    fig.text(0.06, y0 - 0.32 / fig_h, result.headline, ha="left", va="top", fontsize=10, color=INK_2,
             parse_math=False)
    from .value_wedge import low_line
    ll = low_line(result)
    if ll:
        pl = result.price_low or {}
        fig.text(0.06, y0 - 0.55 / fig_h, ll, ha="left", va="top", fontsize=10.5, fontweight="bold",
                 color=BUY if (pl.get("years") or 0) >= 2 else INK_2, parse_math=False)
    fig.text(0.06, y0 - (0.80 if ll else 0.55) / fig_h, f"EPS basis: {inp.eps_basis_label}. Each EPS applies from its release date "
             f"(no look-ahead). Multiples: {inp.multiples_source}.", ha="left", va="top",
             fontsize=8, color=MUTED, parse_math=False)

    lines = ["Why the corridor moved"]
    for i, e in enumerate(events, 1):
        wrapped = textwrap.wrap(e.text, 150)
        lines.append(f"{i:>2}. {e.date:%b %Y}  {wrapped[0]}")
        lines += [f"              {w}" for w in wrapped[1:]]
    if not events:
        lines.append("    No EPS move of 10%+ and no multiple change in the period.")
    for w in inp.warnings:
        lines.append(f"Note: {w}")
    axn.text(0, 1, "\n".join(lines), va="top", ha="left", fontsize=8, family="monospace",
             color=INK, transform=axn.transAxes, parse_math=False)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130, bbox_inches="tight", facecolor="white")
    # Same figure as SVG with real text (not outlines): opens in PowerPoint
    # (Insert > Pictures, then Convert to Shape), Illustrator, Inkscape or
    # Figma with every line, label and colour editable.
    with plt.rc_context({"svg.fonttype": "none"}):
        fig.savefig(out.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out
