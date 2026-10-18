#!/usr/bin/env python3
"""Build the community edition: a copy of this repo that is safe to make public.

    python scripts/build_community.py --out _community

What it does, in order:

1. Copies every tracked-looking file except the paths in community/exclude.txt
   (the money-free ledger, the canaries, AR9's thesis, live dashboard data,
   paid or licensed data, and this machinery itself).
2. Removes every ``<!-- private:start --> ... <!-- private:end -->`` block from
   markdown. Theses then have share counts, position-sized dollar figures and
   weights rewritten to ``x`` (company-scale figures and anything under
   $10,000 are left alone).
3. Switches off every automatic trigger in the workflows (schedule, push,
   pull_request). Nothing runs in the public repo until whoever uses it adds
   their own keys and presses Run; chained runs (workflow_run) still follow a
   manual run.
4. Lays community/overlay/ over the top: empty or made-up example data so the
   code still runs, plus COMMUNITY.md.
5. Runs the leak guard (community profile) over the result and exits 1 if it
   finds anything. A failed guard means nothing is published.

The output folder is a plain directory. The community_publish workflow pushes
it to the public repo as one fresh commit.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from shared.public_safety import scrub_text, strip_private_blocks  # noqa: E402

COMMUNITY = REPO / "community"
EXCLUDE_FILE = COMMUNITY / "exclude.txt"
OVERLAY = COMMUNITY / "overlay"
KEEP_DIRS = ("docs/data", "docs/transcripts", "fundamentals", "data/sws_csv", "data/sws_debug", "outputs")
# workflow_run stays: with no schedules nothing upstream fires on its own, and
# a chain (Bob, then Harry) should still work when someone runs Bob by hand.
REMOVED_TRIGGERS = {"schedule", "push", "pull_request", "pull_request_target"}


def load_patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    ancestors = ["/".join(parts[:i]) for i in range(1, len(parts))]
    for p in patterns:
        if p.endswith("/"):
            d = p.rstrip("/")
            if any(fnmatch.fnmatch(a, d) for a in ancestors):
                return True
        elif fnmatch.fnmatch(rel, p) or ("/" not in p and fnmatch.fnmatch(parts[-1], p)):
            return True
    return False


def strip_triggers(text: str) -> str:
    """Drop automatic triggers from a workflow's ``on:`` block, keep the rest."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_on = False
    skipping = False
    for line in lines:
        if re.match(r"^on:\s*(#.*)?$", line):
            in_on, skipping = True, False
            out.append(line)
            continue
        if in_on:
            if line.strip() and not line.startswith((" ", "#")):
                in_on = skipping = False  # left the on: block
            else:
                m = re.match(r"^  ([a-z_]+):", line)
                if m:
                    skipping = m.group(1) in REMOVED_TRIGGERS
                    if skipping:
                        continue
                elif skipping and (not line.strip() or line.startswith("   ") or line.lstrip().startswith("#")):
                    continue
                elif skipping:
                    skipping = False
        out.append(line)
    result = "".join(out)
    if "workflow_dispatch" not in result:
        result = result.replace("on:\n", "on:\n  workflow_dispatch:\n", 1)
    return result


def build(out: Path) -> list[str]:
    patterns = load_patterns(EXCLUDE_FILE)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copied: list[str] = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith(".git/") or rel.startswith(out.name + "/") or excluded(rel, patterns):
            continue
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".md":
            text = strip_private_blocks(path.read_text(encoding="utf-8"))
            if rel.startswith("theses/"):
                text = scrub_text(text, min_dollars=10_000)
            dest.write_text(text, encoding="utf-8")
        elif rel.startswith(".github/workflows/") and path.suffix in (".yml", ".yaml"):
            dest.write_text(strip_triggers(path.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            shutil.copy2(path, dest)
        copied.append(rel)
    for path in sorted(OVERLAY.rglob("*")):
        if path.is_file():
            rel = path.relative_to(OVERLAY).as_posix()
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out / rel)
            copied.append(rel)
    # Folders the code expects to exist, kept in git with an empty .gitkeep.
    for d in KEEP_DIRS:
        (out / d).mkdir(parents=True, exist_ok=True)
        (out / d / ".gitkeep").touch()
        copied.append(f"{d}/.gitkeep")
    return copied


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO / "_community")
    ap.add_argument("--no-guard", action="store_true", help="build only (never use when publishing)")
    a = ap.parse_args(argv)
    out = a.out if a.out.is_absolute() else (Path.cwd() / a.out)
    files = build(out)
    print(f"community edition: {len(set(files))} files in {out}")
    if a.no_guard:
        return 0
    guard = [sys.executable, str(REPO / "scripts" / "leak_guard.py"), "check", str(out),
             "--profile", "community", "--require-canaries"]
    return subprocess.call(guard)


if __name__ == "__main__":
    raise SystemExit(main())
