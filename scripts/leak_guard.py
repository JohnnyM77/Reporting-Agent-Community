#!/usr/bin/env python3
"""The last check before anything leaves the private repo.

Two profiles, one per way out:

    site       the GitHub Pages artifact (docs/ plus Theo's slides)
    community  the scrubbed copy pushed to the public community repo

Usage:

    python scripts/leak_guard.py scrub-site _pages
    python scripts/leak_guard.py check _pages --profile site --require-canaries
    python scripts/leak_guard.py check _community --profile community --require-canaries

``check`` exits 1 on any hard finding and prints every finding either way.
It never edits files. ``scrub-site`` rewrites the staged Pages copy only
(never docs/ in the repo): weight fields out of Harry's JSON, and weight
phrases out of every page.

The rules live in shared/public_safety.py. The canary list (every real
number from the IRR workbook) is data/private/canaries.txt, written by
scripts/export_ledger.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from shared.public_safety import (  # noqa: E402
    load_allowlist,
    load_canaries,
    scan_tree,
    scrub_obj,
    scrub_text,
)

CANARIES = REPO / "data" / "private" / "canaries.txt"

PROFILES = {
    # Pages: Harry and Theo talk about Johnny's own positions. Bob, Ned and
    # Slinger quote company filings, which legitimately carry share counts and
    # dollar figures, so they only get the exact-number check, as warnings.
    "site": dict(
        personal_globs=["data/harry*.json", "data/theo.json", "theo/**"],
        cto=False,
        canary_hard=False,
        allow_file=REPO / "data" / "private" / "site_allowlist.txt",
    ),
    # Community edition: everything Johnny wrote is personal, and an exact
    # ledger number anywhere at all (even a test fixture) is a leak.
    "community": dict(
        personal_globs=[
            "theses/**", "docs/**", "data/**", "config/**", "watchlists/**", "valuations/**",
            "*.md", "hindsight/*.md", "esther/*.md", "master_engine/*.md", "sunday-sally/*.md",
        ],
        cto=True,
        canary_hard=True,
        allow_file=REPO / "community" / "allowlist.txt",
    ),
}


def scrub_site(root: Path) -> int:
    changed = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".html"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".json" and path.name.startswith("harry"):
            try:
                new = json.dumps(scrub_obj(json.loads(text)), indent=2, ensure_ascii=False)
            except ValueError:
                new = scrub_text(text)
        else:
            # Everything else: weights only. Bob's "$315,000 contract" is a
            # company figure, not Johnny's money.
            new = scrub_text(text, dollars=False)
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed += 1
            print(f"scrubbed {path.relative_to(root)}")
    print(f"scrub-site: {changed} file(s) changed")
    return 0


def check(root: Path, profile: str, canaries_path: Path, require: bool, allow_path: Path | None) -> int:
    cfg = PROFILES[profile]
    canaries = load_canaries(canaries_path)
    if require and not canaries:
        print(f"LEAK GUARD: no canary list at {canaries_path}. Run scripts/export_ledger.py first.")
        return 1
    allow = load_allowlist(allow_path or cfg["allow_file"])
    findings = scan_tree(
        root,
        personal_globs=cfg["personal_globs"],
        canaries=canaries,
        cto=cfg["cto"],
        allow=allow,
        canary_hard=cfg["canary_hard"],
    )
    hard = [f for f in findings if f.hard]
    for f in findings:
        print(f)
    print(
        f"leak guard ({profile}): {len(hard)} leak(s), {len(findings) - len(hard)} warning(s), "
        f"{len(canaries)} canary numbers checked"
    )
    return 1 if hard else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrub-site")
    s.add_argument("root", type=Path)
    c = sub.add_parser("check")
    c.add_argument("root", type=Path)
    c.add_argument("--profile", choices=sorted(PROFILES), required=True)
    c.add_argument("--canaries", type=Path, default=CANARIES)
    c.add_argument("--require-canaries", action="store_true")
    c.add_argument("--allowlist", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.cmd == "scrub-site":
        return scrub_site(a.root)
    return check(a.root, a.profile, a.canaries, a.require_canaries, a.allowlist)


if __name__ == "__main__":
    raise SystemExit(main())
