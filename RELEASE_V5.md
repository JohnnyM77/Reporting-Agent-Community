# V5: private engine, public community edition

Restore point for everything before this: the `v4-final` release.

## What changed

- The repo is private. A scrubbed copy is published separately as the
  community edition (`scripts/build_community.py`, `community_publish.yml`).
- Leak guard (`shared/public_safety.py`, `scripts/leak_guard.py`). Checks for
  position weights, share counts, position-sized dollar figures, the family
  email domain, and every exact number from the IRR workbook. Runs before
  every Pages upload and inside every community build. Any hit stops the run.
- `scripts/export_ledger.py` also writes `data/private/canaries.txt`.
- Harry's public JSON and dashboard card no longer carry position weights,
  and model-written prose is scrubbed of them.
- ABB thesis: the archTIS CTO section is marked private.

## Community edition leaves out

The decision ledger (shipped empty, plus a made-up example), AR9's thesis,
live dashboard data, transcripts, outputs, Simply Wall St exports, the EODHD
cache, and subscription price targets. Workflow schedules and push triggers
are switched off. Share counts and position dollars in the theses become `x`.
