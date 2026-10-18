"""Build the value wedge for one or more tickers, on your own machine.

    cd sunday-sally
    python -m src.wedge_cli PWH
    python -m src.wedge_cli PWH BXB --out ~/Desktop/wedges
    python -m src.wedge_cli PWH --prices-csv pwh_prices.csv   # Date,Close; no internet needed

Per ticker it writes: wedge_chart.png (the picture), wedge_chart.svg (the
same chart, every element editable), value_wedge.xlsx (native Excel charts on
live formulas), wedge_points.csv and wedge.json. No email, no dashboard.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .pathing import repo_root
from .value_wedge import compute_wedge, load_wedge_inputs, normalise_ticker, write_outputs
from .wedge_chart import render_wedge_chart
from .wedge_workbook import build_wedge_workbook


def _csv_prices(path: str) -> pd.Series:
    df = pd.read_csv(path)
    raw = df["Date"].astype(str)
    dates = pd.to_datetime(raw, format="%Y%m%d", errors="coerce").fillna(pd.to_datetime(raw, errors="coerce"))
    s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values, index=dates).dropna()
    return s[s.index.notna()].sort_index()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Draw Sally's value wedge (PNG, SVG, XLSX).")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "outputs" / "wedge"))
    ap.add_argument("--prices-csv", help="Date,Close CSV instead of fetching EODHD prices (one ticker only)")
    ap.add_argument("--start", default="full",
                    help="full | year_before_buy (a year before your first buy in data/decisions.json) | YYYY-MM-DD")
    a = ap.parse_args(argv)

    for raw in a.tickers:
        exch = normalise_ticker(raw)
        prices = _csv_prices(a.prices_csv) if a.prices_csv else None
        result = compute_wedge(load_wedge_inputs(exch, repo=repo_root(), prices=prices, start=a.start))
        folder = Path(a.out).expanduser() / exch.split(".")[0]
        write_outputs(result, folder)
        render_wedge_chart(result, folder / "wedge_chart.png")
        build_wedge_workbook(result, folder / "value_wedge.xlsx")
        print(result.headline)
        for w in result.inputs.warnings:
            print(f"  note: {w}")
        print(f"  -> {folder}")


if __name__ == "__main__":
    main()
