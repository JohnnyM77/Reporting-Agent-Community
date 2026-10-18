"""EODHD is the only market-data source. This fails if anyone brings back a
second one (yfinance, Alpha Vantage, FMP, Yahoo quote/chart endpoints) or a
made-up fallback price series, in agent code or in a workflow install.

Yahoo's *news search* (v1/finance/search) is headlines, not numbers, and
stays allowed for Ned and Sally's news context. Links to a Yahoo quote page
(master_engine/linker.py) are links, not data.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BANNED = [
    (re.compile(r"^\s*(import|from)\s+yfinance\b", re.M), "imports yfinance"),
    (re.compile(r"alphavantage\.co"), "calls Alpha Vantage"),
    (re.compile(r"financialmodelingprep\.com"), "calls FMP"),
    (re.compile(r"finance\.yahoo\.com/v\d+/finance/(chart|quote|quoteSummary)"), "calls Yahoo prices"),
    (re.compile(r"[Ss]ynthetic placeholder"), "invents placeholder prices"),
]
SKIP_DIRS = {"tests", ".claude", ".git", "node_modules", "__pycache__", "site"}


def _agent_python_files():
    for p in REPO.rglob("*.py"):
        if SKIP_DIRS & set(p.relative_to(REPO).parts) or "tests" in p.parts:
            continue
        yield p


def test_no_second_market_data_source_in_agent_code():
    hits = []
    for p in _agent_python_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        hits += [f"{p.relative_to(REPO)}: {why}" for rx, why in BANNED if rx.search(text)]
    assert not hits, "Market data must come from shared/eodhd.py only:\n" + "\n".join(hits)


def test_workflows_and_requirements_do_not_install_yfinance():
    files = list((REPO / ".github" / "workflows").glob("*.yml")) + list(REPO.rglob("requirements*.txt"))
    hits = [str(f.relative_to(REPO)) for f in files
            if re.search(r"\byfinance\b", f.read_text(encoding="utf-8", errors="replace"))]
    assert not hits, f"yfinance is still installed by: {hits}"


def test_every_market_data_workflow_gets_the_eodhd_token():
    # The workflows whose agents read prices or fundamentals.
    for name in ("wally_watchlists", "sunday_sally_weekly_review", "sally_wedge",
                 "captain_hindsight", "esther", "results_pack_agent", "eodhd_check",
                 "daily"):
        text = (REPO / ".github" / "workflows" / f"{name}.yml").read_text(encoding="utf-8")
        assert "EODHD_API_TOKEN: ${{ secrets.EODHD_API_TOKEN }}" in text, name
