# Community repository — what differs

The companion repository [Reporting-Agent-Community](https://github.com/JohnnyM77/Reporting-Agent-Community) shares a large amount of application code with the private repository, but it is a separately published community edition.

**Confirmed in repository notes:** the private repo’s Pages site and community edition are both public surfaces. The private repo contains community-build machinery and overlays. The public edition intentionally does not expose the same private portfolio sizing data as the private repository.

Key files in the private repo:
- [`scripts/build_community.py`](../scripts/build_community.py) — builds the community edition.
- [`community/overlay/COMMUNITY.md`](../community/overlay/COMMUNITY.md) — community overlay/instructions.
- [`community/allowlist.txt`](../community/allowlist.txt) and [`community/exclude.txt`](../community/exclude.txt) — publication controls.
- [`shared/public_safety.py`](../shared/public_safety.py) and [`scripts/leak_guard.py`](../scripts/leak_guard.py) — output safety checks.

Do not assume a file or data value in the private repository is safe to copy into a public page simply because a similar file exists in the community repository. Use the publishing controls and verify the generated output.
