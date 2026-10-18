"""Command line.

    python -m mickys_macro run --mode incremental|backfill|daily|weekly [--no-email]
"""

from __future__ import annotations

import argparse
import sys

from .main import run
from .store import StoreConfigError


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m mickys_macro", description="Micky's Macro")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ingest new research and build the brief")
    r.add_argument("--mode", default="daily", choices=["incremental", "backfill", "daily", "weekly"])
    r.add_argument("--no-email", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = run(mode=args.mode, send=not args.no_email)
    except StoreConfigError as exc:
        print(f"[mickys_macro] STORE MISCONFIGURED: {exc}", file=sys.stderr)
        return 2
    print(f"[mickys_macro] {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
