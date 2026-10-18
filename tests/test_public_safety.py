"""The rules that decide what may be published (shared/public_safety.py),
the leak guard CLI, and the community-edition builder."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from shared.public_safety import (
    canary_regex,
    glob_match,
    scan_tree,
    scrub_obj,
    scrub_text,
    strip_private_blocks,
)

REPO = Path(__file__).resolve().parent.parent


def _load(rel: str):
    spec = importlib.util.spec_from_file_location(rel.replace("/", "_"), REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# scrub_text / scrub_obj
# ---------------------------------------------------------------------------


def test_weights_are_scrubbed_from_prose():
    s = scrub_text("an accidental 9% overweight from intentional 3% sizing; 7.5% of portfolio; "
                   "trim to 4-5% of capital; weight of 6%")
    assert "9%" not in s and "3%" not in s and "7.5%" not in s and "4-5%" not in s and "6%" not in s
    assert s.count("x%") == 5


def test_company_context_is_left_alone():
    s = scrub_text("revenue $4,180m, 25% of book, margin 31%, up 12% on pcp, a $2.3bn pipeline")
    assert s == "revenue $4,180m, 25% of book, margin 31%, up 12% on pcp, a $2.3bn pipeline"


def test_position_money_and_share_counts_are_scrubbed():
    s = scrub_text("$987,654 in, 54,321 shares, worth $1,234,567, net loss ~A$85k.")
    assert s == "$x in, x shares, worth $x, net loss ~A$x."


def test_min_dollars_keeps_small_story_figures():
    s = scrub_text("turnover of $2,231 on the day; a $90,000 order", min_dollars=10_000)
    assert "$2,231" in s and "$90,000" not in s


def test_scrubbed_text_stays_valid_yaml():
    import yaml

    doc = "claim: 54,321 shares bought at $1.00\nnote: $987,654 in\n"
    assert yaml.safe_load(scrub_text(doc)) == {"claim": "x shares bought at $1.00", "note": "$x in"}


def test_scrub_obj_drops_weight_keys_everywhere():
    obj = {"a": 1, "weight_of_book_pct": 9.1, "nested": [{"weight_if_new": "3%", "verdict": "a 9% overweight"}]}
    out = scrub_obj(obj)
    assert out == {"a": 1, "nested": [{"verdict": "a x% overweight"}]}


def test_private_blocks_are_removed():
    text = "keep\n<!-- private:start -->\nsecret\n<!-- private:end -->\nalso keep\n"
    assert strip_private_blocks(text) == "keep\nalso keep\n"


# ---------------------------------------------------------------------------
# canaries and scope
# ---------------------------------------------------------------------------


def test_canary_matches_figures_not_tokens():
    rx = canary_regex([987654, 4321])
    assert rx.search("worth $987,654 now") and rx.search("value 987654.20")
    assert rx.search("cost 4,321")
    assert not rx.search("color #4321ab") and not rx.search("abc4321def")
    assert not rx.search("4321")  # bare four digits never match
    assert not rx.search("1,987,654") and not rx.search("data:image/png;base64,QQ987654+/")


def test_glob_star_stays_in_one_folder():
    assert glob_match("README.md", "*.md")
    assert not glob_match(".claude/skills/x/README.md", "*.md")
    assert glob_match("theo/a/b.html", "theo/**")
    assert glob_match("data/harry_theses.json", "data/harry*.json")


def test_guard_finds_each_kind_of_leak(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/harry.json").write_text(json.dumps({"reports": [
        {"weight_of_book_pct": 9.0, "verdict": "the position is 9% of portfolio"}]}))
    (tmp_path / "theses").mkdir()
    (tmp_path / "theses/X.md").write_text("54,321 shares for $987,654.\nMy " + "brother is the C" + "TO there.\n"
                                           "Contact " + "me@myerscough" + "s.com\n")
    (tmp_path / "data/bob.json").write_text(json.dumps({"title": "Placement of 5,000,000 shares at $1.20"}))
    findings = scan_tree(tmp_path, personal_globs=["data/harry*.json", "theses/**"],
                         canaries=[987654], cto=True)
    rules = {(f.path, f.rule) for f in findings if f.hard}
    assert ("data/harry.json", "weight field") in rules
    assert ("data/harry.json", "position weight") in rules
    assert ("theses/X.md", "share count") in rules
    assert ("theses/X.md", "dollar amount") in rules
    assert ("theses/X.md", "exact ledger number") in rules
    assert ("theses/X.md", "relative inside an investee company") in rules
    assert ("theses/X.md", "family email domain") in rules
    assert not any(f.path == "data/bob.json" and f.hard for f in findings)


def test_site_scrub_then_check(tmp_path):
    guard = _load("scripts/leak_guard.py")
    site = tmp_path / "_pages"
    (site / "data").mkdir(parents=True)
    (site / "data/harry.json").write_text(json.dumps({"reports": [
        {"weight_of_book_pct": 9.0, "position": {"unrealised_pct": -5, "weight_of_book_pct": 9.0},
         "verdict": "an accidental 9% overweight"}]}))
    (site / "index.html").write_text("<p>an accidental 9% overweight</p><p>Placement $315,000</p>")
    canaries = tmp_path / "c.txt"
    canaries.write_text("987654\n")
    assert guard.check(site, "site", canaries, True, tmp_path / "none.txt") == 1
    guard.scrub_site(site)
    assert guard.check(site, "site", canaries, True, tmp_path / "none.txt") == 0
    data = json.loads((site / "data/harry.json").read_text())
    assert "weight_of_book_pct" not in json.dumps(data)
    assert "$315,000" in (site / "index.html").read_text()  # company figure survives


def test_guard_refuses_to_run_without_canaries_when_required(tmp_path):
    guard = _load("scripts/leak_guard.py")
    (tmp_path / "site").mkdir()
    assert guard.check(tmp_path / "site", "site", tmp_path / "missing.txt", True, None) == 1


# ---------------------------------------------------------------------------
# community builder
# ---------------------------------------------------------------------------


def test_exclude_patterns():
    import pytest

    if not (REPO / "community" / "exclude.txt").is_file():
        pytest.skip("community/ is not shipped in the community edition itself")
    b = _load("scripts/build_community.py")
    pats = b.load_patterns(REPO / "community" / "exclude.txt")
    for rel in ("data/private/canaries.txt", "data/decisions.json", "theses/AR9.md",
                "docs/data/harry.json", "fundamentals/abb_ax.json", "tests/__pycache__/x.pyc",
                "community/exclude.txt", ".github/workflows/community_publish.yml"):
        assert b.excluded(rel, pats), rel
    for rel in ("theses/ABB.md", "shared/public_safety.py", "README.md", "watchlists/jm_watchlist.yaml"):
        assert not b.excluded(rel, pats), rel


def test_workflow_triggers_are_switched_off():
    import yaml

    b = _load("scripts/build_community.py")
    src = (
        "name: X\n\non:\n  workflow_dispatch:\n    inputs:\n      a:\n        type: string\n"
        "  schedule:\n    # every day\n    - cron: \"0 1 * * *\"\n"
        "  push:\n    branches: [main]\n    paths:\n      - \"x/**\"\n"
        "  workflow_run:\n    workflows: [\"Y\"]\n    types: [completed]\n\njobs:\n  a:\n    runs-on: ubuntu-latest\n"
    )
    out = yaml.safe_load(b.strip_triggers(src))
    on = out[True] if True in out else out["on"]
    assert set(on) == {"workflow_dispatch", "workflow_run"}
    assert "jobs" in out


def test_every_real_workflow_still_parses_after_stripping():
    import yaml

    b = _load("scripts/build_community.py")
    for wf in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        out = yaml.safe_load(b.strip_triggers(wf.read_text(encoding="utf-8")))
        on = out.get(True, out.get("on"))
        assert "workflow_dispatch" in on, wf.name
        assert not ({"schedule", "push", "pull_request"} & set(on or {})), wf.name
