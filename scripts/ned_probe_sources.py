#!/usr/bin/env python3
"""Check that every source in media_sources.yaml responds, without running Ned.

    python scripts/ned_probe_sources.py

Static RSS feeds: HTTP status and item count. Google News searches: one sample
query. Newsletter web archives: the last few dates. Newsletter inboxes: whether
IMAP credentials are set and log in (never prints the address or password).
Run from Actions via "Ned News Agent" -> Run workflow -> probe_only.
"""

from __future__ import annotations

import imaplib
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ned.newsletter_scanner import _archive_dates, _WEB_HEADERS, imap_credentials  # noqa: E402


def _count_items(content: bytes) -> int:
    root = ET.fromstring(content)
    return len(root.findall(".//item")) + len(root.findall(".//{http://www.w3.org/2005/Atom}entry"))


def main() -> int:
    media = yaml.safe_load((ROOT / "media_sources.yaml").read_text(encoding="utf-8")) or {}
    bad = 0
    print("RSS feeds")
    for feed in media.get("rss_feeds", []):
        url = feed["url"]
        if "{query}" in url:
            q = '"Brambles"'
            if feed.get("type") == "google_news_sites":
                q += " (" + " OR ".join(f"site:{s}" for s in feed.get("sites", [])) + ")"
            url = url.replace("{query}", urllib.parse.quote_plus(q))
        try:
            r = requests.get(url, headers=_WEB_HEADERS, timeout=20)
            n = _count_items(r.content) if r.status_code == 200 else 0
            ok = r.status_code == 200 and n > 0
            print(f"  {'OK  ' if ok else 'FAIL'} {feed.get('label')}: HTTP {r.status_code}, {n} items")
        except Exception as exc:
            ok = False
            print(f"  FAIL {feed.get('label')}: {type(exc).__name__}: {exc}")
        bad += 0 if ok else 1

    print("Newsletters")
    for nl in media.get("newsletters", []):
        if nl.get("web_archive"):
            found = []
            for d in _archive_dates(72, nl.get("timezone", "Australia/Sydney")):
                try:
                    r = requests.get(nl["web_archive"].replace("{date}", d), headers=_WEB_HEADERS, timeout=20)
                    found.append(f"{d}:{r.status_code}")
                except Exception as exc:
                    found.append(f"{d}:{type(exc).__name__}")
            print(f"  {nl['label']} web archive: {', '.join(found)}")
    user, pw, host = imap_credentials()
    if not (user and pw):
        print("  Inbox: not configured (NED_IMAP_USER / NED_IMAP_PASSWORD)")
    else:
        try:
            c = imaplib.IMAP4_SSL(host, timeout=30)
            c.login(user, pw)
            c.logout()
            print("  Inbox: login OK")
        except Exception as exc:
            print(f"  Inbox: login FAILED ({type(exc).__name__})")
            bad += 1
    print(f"{bad} source(s) failing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
