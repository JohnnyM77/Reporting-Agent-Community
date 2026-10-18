"""The value wedge as an Excel workbook you can play with.

Nothing on the Chart sheet is a picture: every line is a native Excel chart
driven by formulas on the Weekly sheet, which read the EPS and Multiples
sheets. Change a BUY or SELL PE, add a multiple-change row, or correct an EPS
figure, and the corridor, PE panel and wedge panels redraw.

Sheets:
  Read me      what is where, how to edit
  Chart        four native charts (price vs corridor, PE, $ wedge, % wedge)
  Weekly       one row per week: price (values) + every derived column (formulas)
  EPS          the EPS history (blue cells are inputs)
  Multiples    BUY / SELL PE history (blue cells are inputs)
  Story        why the corridor moved, the seven diagnostics, data notes
               (text as computed by Sally on the run date; not live)
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from .value_wedge import WedgeResult

NAVY = "1F2D4E"
BLUE_INPUT = "0000FF"
PRICE = "2A78D6"
BUY = "008300"
SELL = "E34948"
WEDGE = "4A3AA7"
PE = "EB6834"


def build_wedge_workbook(result: WedgeResult, output_path: str | Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import AreaChart, LineChart, Reference
    from openpyxl.chart.shapes import GraphicalProperties
    from openpyxl.drawing.line import LineProperties
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    inp = result.inputs
    t = inp.ticker.split(".")[0]
    wb = Workbook()
    readme = wb.active
    readme.title = "Read me"
    chart_ws = wb.create_sheet("Chart")
    weekly = wb.create_sheet("Weekly")
    eps_ws = wb.create_sheet("EPS")
    mult_ws = wb.create_sheet("Multiples")
    story = wb.create_sheet("Story")
    fc_ws = wb.create_sheet("Forecast") if result.forecast else None

    hdr_font = Font(bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor=NAVY)
    input_font = Font(color=BLUE_INPUT)

    def header(ws, cols, widths=None):
        for i, c in enumerate(cols, 1):
            cell = ws.cell(1, i, c)
            cell.font, cell.fill = hdr_font, hdr_fill
            cell.alignment = Alignment(wrap_text=True, vertical="center")
            if widths:
                ws.column_dimensions[get_column_letter(i)].width = widths[i - 1]
        ws.freeze_panes = "A2"

    # ── EPS ────────────────────────────────────────────────────────────────
    eps_ccy = inp.eps_currency or "share-price currency"
    eps_head = f"{'Smoothed ' if inp.smoothing else ''}EPS used (cents, {eps_ccy})"
    header(eps_ws, ["Applies from (release date)", "Period", eps_head, "Source", "Notes",
                    f"Reported EPS (cents, {eps_ccy})"], [16, 14, 14, 40, 90, 14])
    earnings = sorted(inp.earnings, key=lambda e: e.date)
    for r, e in enumerate(earnings, 2):
        eps_ws.cell(r, 1, e.date).number_format = "yyyy-mm-dd"
        eps_ws.cell(r, 2, e.period)
        c = eps_ws.cell(r, 3, e.eps_used)
        c.font, c.number_format = input_font, "0.000"
        eps_ws.cell(r, 4, e.source)
        eps_ws.cell(r, 5, e.notes)
        eps_ws.cell(r, 6, e.eps_cents).number_format = "0.000"
    n_eps = len(earnings) + 1
    # Spare rows so new results can be typed in without touching formulas.
    eps_last = n_eps + 10

    # ── Multiples ──────────────────────────────────────────────────────────
    header(mult_ws, ["Effective from", "BUY PE (x)", "SELL PE (x)", "Reason / source"], [16, 12, 12, 80])
    for r, m in enumerate(sorted(inp.multiples, key=lambda m: m.date), 2):
        mult_ws.cell(r, 1, m.date).number_format = "yyyy-mm-dd"
        for col, v in ((2, m.buy_pe), (3, m.sell_pe)):
            c = mult_ws.cell(r, col, v)
            c.font = input_font
        mult_ws.cell(r, 4, m.reason or m.source)
    mult_last = len(inp.multiples) + 1 + 10
    mult_ws.column_dimensions["F"].width, mult_ws.column_dimensions["G"].width = 30, 10
    mult_ws.cell(1, 6, "Fair value split (0 = BUY, 1 = SELL)").font = Font(bold=True)
    c = mult_ws.cell(1, 7, inp.fair_split if inp.fair_split is not None else 0.3)
    c.font, c.number_format = input_font, "0.00"
    mult_ws.cell(len(inp.multiples) + 3, 1,
                 "Add a row (date + BUY PE + SELL PE) to change the framework from that date. "
                 "Keep rows in date order.").font = Font(italic=True, color="52514E")

    # ── Weekly (formulas) ──────────────────────────────────────────────────
    cols = ["Week ending", "Share price", "EPS in force (c)", "BUY PE", "SELL PE", "BUY value",
            "SELL value", "Wedge band (SELL-BUY)", "Actual PE", "Abs wedge ($)", "Rel wedge",
            "Position (0=BUY, 1=SELL)", "Zone", "New 52-week high",
            (f"FX ({inp.fx_label})" if inp.eps_currency else "FX (1 = EPS already in share-price currency)"),
            "Chart: base (min price, BUY)", "Chart: buying zone", "Chart: wedge band", "Chart: selling zone",
            "Fair value", "FY label", "Chart: forecast band", "Forecast?"]
    header(weekly, cols, [12, 11, 12, 9, 9, 11, 11, 13, 10, 11, 10, 13, 22, 10, 14, 12, 11, 11, 11, 11, 8, 11, 9])
    E = f"EPS!$A$2:$A${eps_last}"
    Ev = f"EPS!$C$2:$C${eps_last}"
    M = f"Multiples!$A$2:$A${mult_last}"
    Mb = f"Multiples!$B$2:$B${mult_last}"
    Ms = f"Multiples!$C$2:$C${mult_last}"
    pts = result.points
    # Forecast weeks to the right of today: no price, EPS from the Forecast
    # sheet (first case), so the band carries on like the PNG.
    fc_case = inp.forecast_cases[0]["label"] if inp.forecast_cases else None
    fc_dates: list = []
    if result.forecast and pts:
        fc_end = inp.forecast_end or (max(r["date"] for r in result.forecast) + dt.timedelta(days=182))
        d = pts[-1].date + dt.timedelta(days=7)
        while d <= fc_end:
            fc_dates.append(d)
            d += dt.timedelta(days=7)
    n_fc = len(result.forecast)
    FCd, FCc, FCv = (f"Forecast!$C$2:$C${n_fc + 1}", f"Forecast!$A$2:$A${n_fc + 1}", f"Forecast!$D$2:$D${n_fc + 1}")
    fem = inp.fy_end_month or 12
    rows_out = [(p.date, p) for p in pts] + [(d, None) for d in fc_dates]
    last_fx = (pts[-1].fx or 1) if pts else 1
    prev_fy = None
    for i, (day, p) in enumerate(rows_out):
        r = i + 2
        weekly.cell(r, 1, day).number_format = "yyyy-mm-dd"
        if p is not None:
            weekly.cell(r, 2, round(p.price, 4)).number_format = '"$"0.00'
        weekly.cell(r, 15, round(p.fx, 6) if (p is not None and p.fx) else round(last_fx, 6)).number_format = "0.0000"
        # FY label once per financial year, in the week nearest the year's middle
        fy = day.year + (1 if day.month > fem else 0)
        mid = dt.date(fy - 1 if fem < 12 else fy, (fem % 12) + 1, 1) + dt.timedelta(days=182)
        if fy != prev_fy and day >= mid - dt.timedelta(days=3):
            weekly.cell(r, 21, f"FY{fy % 100:02d}" + ("F" if p is None else ""))
            prev_fy = fy
        else:
            weekly.cell(r, 21, "")
        eps_hist = f'LOOKUP(2,1/(({E}<=A{r})*({Ev}<>"")),{Ev})'
        eps_f = (f'IFERROR(LOOKUP(2,1/(({FCd}<=A{r})*({FCc}="{fc_case}")),{FCv}),{eps_hist})'
                 if (p is None and fc_case) else eps_hist)
        f = {
            # LOOKUP(2, 1/(test), values) = the last row where test is true:
            # the latest figure released on or before this week. Blank spare
            # rows and out-of-order rows are ignored.
            3: f'=IFERROR({eps_f}*O{r},NA())',
            4: f'=IFERROR(LOOKUP(2,1/(({M}<=A{r})*({Mb}<>"")),{Mb}),Multiples!$B$2)',
            5: f'=IFERROR(LOOKUP(2,1/(({M}<=A{r})*({Ms}<>"")),{Ms}),Multiples!$C$2)',
            6: f"=IF(AND(ISNUMBER(C{r}),C{r}>0),C{r}/100*D{r},NA())",
            7: f"=IF(AND(ISNUMBER(C{r}),C{r}>0),C{r}/100*E{r},NA())",
            8: f"=IF(ISNUMBER(F{r}),G{r}-F{r},NA())",
            9: f"=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r}),C{r}>0),B{r}/(C{r}/100),NA())",
            10: f"=IF(ISNUMBER(F{r}),G{r}-F{r},NA())",
            11: f"=E{r}/D{r}-1",
            12: f"=IF(ISNUMBER(F{r}),(B{r}-F{r})/(G{r}-F{r}),NA())",
            13: (f'=IF(NOT(ISNUMBER(L{r})),"No valuation",IF(L{r}<0,"Below BUY",IF(L{r}<=1/3,'
                 f'"Lower third of wedge",IF(L{r}<=2/3,"Middle of wedge",IF(L{r}<=1,'
                 f'"Upper third of wedge","Above SELL")))))'),
            14: (f'=IF(B{r}>=MAX(B{max(2, r - 51)}:B{r}),1,"")' if (r >= 53 and p is not None) else ""),
            # Stacked-area pieces for the chart (blank = 0 to Excel's stacking):
            16: f'=IF(ISNUMBER(F{r}),IF(ISNUMBER(B{r}),MIN(B{r},F{r}),F{r}),NA())',
            17: f'=IF(AND(ISNUMBER(F{r}),ISNUMBER(B{r})),MAX(F{r}-B{r},0),0)',
            18: f'=IF(AND(ISNUMBER(F{r}),W{r}<>1),G{r}-F{r},0)',
            19: f'=IF(AND(ISNUMBER(G{r}),ISNUMBER(B{r})),MAX(B{r}-G{r},0),0)',
            20: f'=IF(ISNUMBER(F{r}),F{r}+Multiples!$G$1*(G{r}-F{r}),NA())',
            22: f'=IF(AND(ISNUMBER(F{r}),W{r}=1),G{r}-F{r},0)',
        }
        weekly.cell(r, 23, 1 if p is None else 0)
        fmt = {3: "0.00", 4: "0.0", 5: "0.0", 6: '"$"0.00', 7: '"$"0.00', 8: '"$"0.00',
               9: "0.0", 10: '"$"0.00', 11: "0%", 12: "0%", 16: '"$"0.00', 17: '"$"0.00', 18: '"$"0.00',
               19: '"$"0.00', 20: '"$"0.00', 22: '"$"0.00'}
        if p is None:      # forecast week: no price, so no actual PE, position or zone (empty = a gap)
            for k in (9, 12, 13, 14):
                f.pop(k, None)
        for col, formula in f.items():
            c = weekly.cell(r, col, formula)
            if col in fmt:
                c.number_format = fmt[col]
    last = len(rows_out) + 1

    # ── Charts ─────────────────────────────────────────────────────────────
    cats = Reference(weekly, min_col=1, min_row=2, max_row=last)
    # One tick a year in the middle of each financial year, labelled FY27 etc.
    # For a June year end the middle is 1 Jan, whose calendar year IS the FY
    # number, so a '"FY"yy' date format labels it correctly (Dec year end: 1 Jul).
    first_day = rows_out[0][0] if rows_out else dt.date.today()
    mid_month = (fem % 12) + 7 if (fem % 12) + 7 <= 12 else (fem % 12) - 5
    tick0 = dt.date(first_day.year, mid_month, 1)
    if tick0 < first_day:
        tick0 = dt.date(first_day.year + 1, mid_month, 1)
    serial0 = (tick0 - dt.date(1899, 12, 30)).days
    serial_last = ((rows_out[-1][0] if rows_out else dt.date.today()) - dt.date(1899, 12, 30)).days
    skip = max(1, round(len(pts) / 10))

    def style(series, colour, width_pt=1.75, dash=None, nofill=False):
        series.graphicalProperties = GraphicalProperties()
        series.graphicalProperties.line = LineProperties(solidFill=colour, w=int(width_pt * 12700))
        if dash:
            series.graphicalProperties.line.prstDash = dash
        if nofill:
            series.graphicalProperties.noFill = True
        series.smooth = False

    def base(chart, title, y_title, y_fmt):
        from openpyxl.chart.axis import DateAxis
        from openpyxl.chart.text import RichText
        from openpyxl.drawing.text import CharacterProperties, Paragraph, ParagraphProperties, RichTextProperties
        chart.title = title
        chart.y_axis.title = y_title or None
        chart.y_axis.number_format = y_fmt
        chart.y_axis.majorGridlines = None
        chart.x_axis = DateAxis(crossAx=100)
        from openpyxl.chart.data_source import NumFmt
        chart.x_axis.numFmt = NumFmt(formatCode='"FY"yy', sourceLinked=False)
        chart.x_axis.majorTimeUnit = "months"
        chart.x_axis.majorUnit = 12
        chart.x_axis.scaling.min = serial0
        chart.x_axis.scaling.max = serial_last
        chart.x_axis.txPr = RichText(bodyPr=RichTextProperties(rot=0, vert="horz"),
                                     p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties(sz=900, b=True)),
                                                  endParaRPr=CharacterProperties(sz=900, b=True))])
        chart.y_axis.delete = False
        chart.x_axis.delete = False
        chart.legend.position = "t"
        chart.width, chart.height = 34, 12

    def area_style(series, fill=None, alpha=None):
        series.graphicalProperties = GraphicalProperties()
        if fill is None:
            series.graphicalProperties.noFill = True
        else:
            series.graphicalProperties.solidFill = fill
        series.graphicalProperties.line = LineProperties(noFill=True)

    # 1. Price vs the wedge, drawn like the PNG: stacked areas give the grey
    # band and the green / red zones, lines give price, BUY, SELL and fair.
    area = AreaChart(grouping="stacked")
    for col in (16, 17, 18, 19, 22):
        area.add_data(Reference(weekly, min_col=col, min_row=1, max_row=last), titles_from_data=True)
    area.set_categories(cats)
    s_base, s_buyzone, s_band, s_sellzone, s_fband = area.series
    from openpyxl.chart.legend import LegendEntry
    from openpyxl.chart.series import SeriesLabel
    for s_, name in zip(area.series, ("base", "Price below BUY: buying zone", "Wedge: BUY to SELL",
                                      "Price above SELL: selling zone",
                                      f"Forecast wedge ({fc_case or 'forecast'}, not reported)")):
        s_.tx = SeriesLabel(v=name)
    area_style(s_base)
    area_style(s_buyzone, "B5DDB8")      # green: price below BUY
    area_style(s_band, "ECEBE6")         # neutral corridor
    area_style(s_sellzone, "F4C7C6")     # red: price above SELL
    area_style(s_fband, "E4E1EF")        # forecast corridor, lighter and tinted
    lines = LineChart()
    for col in (2, 6, 7, 20):
        lines.add_data(Reference(weekly, min_col=col, min_row=1, max_row=last), titles_from_data=True)
    for s_, colour, w, dash, name in zip(lines.series, (PRICE, BUY, SELL, "52514E"), (1.25, 2, 2, 1.25),
                                         (None, None, None, "dash"),
                                         ("Share price (weekly close)", "BUY value", "SELL value", "Fair value")):
        style(s_, colour, w, dash)
        s_.marker.symbol = "none"
        s_.tx = SeriesLabel(v=name)
    # The line chart is the primary (it owns the FY date axis, which LibreOffice
    # will not draw for an area chart); the areas share its axes. Excel and
    # LibreOffice both paint areas behind lines.
    lines.set_categories(cats)
    base(area, f"{inp.company_name} ({t}): the wedge between BUY and SELL", f"Price ({inp.currency}$)", '"$"0.00')
    lines.x_axis = area.x_axis           # one shared FY date axis; areas first so lines sit on top
    lines.y_axis = area.y_axis
    area += lines
    area.legend.legendEntry = [LegendEntry(idx=0, delete=True)]     # the invisible base
    if not fc_dates:
        area.legend.legendEntry.append(LegendEntry(idx=4, delete=True))
    chart_ws.add_chart(area, "A1")

    # 2. PE panel
    pe = LineChart()
    for col in (9, 4, 5):
        pe.add_data(Reference(weekly, min_col=col, min_row=1, max_row=last), titles_from_data=True)
    pe.set_categories(cats)
    for s, colour, dash in zip(pe.series, (PE, BUY, SELL), (None, "dash", "dash")):
        style(s, colour, 1.5, dash)
        s.marker.symbol = "none"
    base(pe, "Actual PE vs BUY / SELL PE (the multiple effect)", "PE (x)", "0")
    sell_max = max((m.sell_pe for m in inp.multiples), default=50)
    pe.y_axis.scaling.min, pe.y_axis.scaling.max = 0, round(sell_max * 2.2)
    pe.height = 8
    chart_ws.add_chart(pe, "A25")

    # 3. Absolute wedge
    aw = AreaChart()
    aw.add_data(Reference(weekly, min_col=10, min_row=1, max_row=last), titles_from_data=True)
    aw.set_categories(cats)
    aw.series[0].graphicalProperties = GraphicalProperties(solidFill="DCD8F0")
    aw.series[0].graphicalProperties.line = LineProperties(solidFill=WEDGE, w=15875)
    base(aw, "Absolute wedge: SELL - BUY in $ per share (moves with EPS)", "$ per share", '"$"0.00')
    aw.height = 6.5
    chart_ws.add_chart(aw, "A42")

    # 4. Relative wedge
    rw = LineChart()
    rw.add_data(Reference(weekly, min_col=11, min_row=1, max_row=last), titles_from_data=True)
    rw.set_categories(cats)
    style(rw.series[0], WEDGE, 2)
    rw.series[0].marker.symbol = "none"
    base(rw, "Relative wedge: SELL PE / BUY PE - 1 (moves only when the multiples change)", "", "0%")
    rel_max = max((m.relative_wedge for m in inp.multiples), default=1)
    rw.y_axis.scaling.min, rw.y_axis.scaling.max = 0, round(rel_max * 1.5, 2)
    rw.height = 6.5
    chart_ws.add_chart(rw, "A56")

    # ── Story ──────────────────────────────────────────────────────────────
    story.column_dimensions["A"].width = 14
    story.column_dimensions["B"].width = 150
    row = 1
    story.cell(row, 1, f"As computed by Sally on {dt.date.today():%d %b %Y}. Text, not live formulas.").font = Font(italic=True)
    row += 2
    story.cell(row, 1, result.headline).font = Font(bold=True, size=12)
    row += 2
    story.cell(row, 1, "Why the corridor moved").font = Font(bold=True)
    row += 1
    for i, e in enumerate(result.events, 1):
        story.cell(row, 1, e.date).number_format = "mmm yyyy"
        story.cell(row, 2, f"{i}. {e.text}").alignment = Alignment(wrap_text=True)
        row += 1
    row += 1
    story.cell(row, 1, "The seven questions").font = Font(bold=True)
    row += 1
    for q, a in result.diagnostics:
        story.cell(row, 1, "Q").font = Font(bold=True)
        story.cell(row, 2, q).font = Font(bold=True)
        story.cell(row + 1, 2, a).alignment = Alignment(wrap_text=True)
        row += 2
    if inp.warnings:
        row += 1
        story.cell(row, 1, "Data notes").font = Font(bold=True)
        row += 1
        for w in inp.warnings:
            story.cell(row, 2, w).alignment = Alignment(wrap_text=True)
            row += 1

    # ── Forecast (not reported; inputs in blue, values are formulas) ───────
    if fc_ws is not None:
        header(fc_ws, ["Case", "Period", "Expected release", "EPS (c) on the wedge's basis - assumption",
                       "BUY PE", "SELL PE", "Fair split", "BUY $", "Fair $", "SELL $", "Price today",
                       "Today's price / EPS (x)", "Note"],
               [16, 10, 14, 16, 9, 9, 10, 10, 10, 10, 11, 14, 90])
        for i, r in enumerate(result.forecast, 2):
            basis = r.get("eps_basis_cents", r["eps_cents"])
            fc_ws.cell(i, 1, r.get("case") or "")
            fc_ws.cell(i, 2, f"{r['period']}F")
            fc_ws.cell(i, 3, r["date"]).number_format = "dd-mmm-yy"
            for col, v in ((4, basis), (5, r["buy_pe"]), (6, r["sell_pe"]), (7, inp.fair_split or 0)):
                fc_ws.cell(i, col, v).font = input_font
            fc_ws.cell(i, 8, f"=D{i}*E{i}/100").number_format = '"$"#,##0.00'
            fc_ws.cell(i, 9, f"=D{i}*(E{i}+G{i}*(F{i}-E{i}))/100").number_format = '"$"#,##0.00'
            fc_ws.cell(i, 10, f"=D{i}*F{i}/100").number_format = '"$"#,##0.00'
            fc_ws.cell(i, 11, r.get("price_today")).number_format = '"$"#,##0.00'
            fc_ws.cell(i, 12, f'=IF(D{i}>0,K{i}/(D{i}/100),"")').number_format = "0.0"
            note = r.get("note") or ""
            if abs(basis - r["eps_cents"]) > 0.05:
                note = f"Reported-basis EPS {r['eps_cents']:.1f}c; wedge basis {basis:.1f}c. " + note
            fc_ws.cell(i, 13, note)
        n = len(result.forecast) + 3
        fc_ws.cell(n, 1, f"{inp.forecast_label}: an assumption, not reported earnings.").font = Font(bold=True)
        if inp.forecast_basis:
            fc_ws.cell(n + 1, 1, inp.forecast_basis).alignment = Alignment(wrap_text=True)

    # ── Read me ────────────────────────────────────────────────────────────
    readme.column_dimensions["A"].width = 120
    lines_txt = [
        f"{inp.company_name} ({t}): the value wedge between BUY and SELL",
        "",
        "Chart: four native Excel charts. Click any line to restyle it; right-click > Select Data to change what it plots.",
        "Weekly: share prices are values; every other column is a formula reading EPS and Multiples.",
        "EPS: blue cells are inputs. Each EPS applies from its release date onward (no look-ahead).",
        "      To add a result, type it into the blank rows below the last one (up to 10 spare rows).",
        "Multiples: blue cells are inputs. Change BUY or SELL PE, or add a dated row to change the framework from that date.",
        "Story: Sally's narrative and the seven questions as computed on the run date (text; it does not update).",
        "",
        "BUY value = EPS in force x BUY PE in force.   SELL value = EPS in force x SELL PE in force.",
        "Absolute wedge = SELL - BUY ($): grows when EPS grows.   Relative wedge = SELL PE / BUY PE - 1: moves only with the multiples.",
        "",
        f"EPS basis: {inp.eps_basis_label}.",
        f"Multiples: {inp.multiples_source}.",
        "Prices: EODHD daily close (raw, unadjusted), last trading day of each week.",
    ]
    for i, txt in enumerate(lines_txt, 1):
        readme.cell(i, 1, txt)
    readme["A1"].font = Font(bold=True, size=14)

    wb.active = wb.sheetnames.index("Chart")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out
