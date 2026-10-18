# ned/news_scanner.py
#
# Scans Google News RSS and static RSS feeds for portfolio company mentions.
# Uses Yahoo Finance news (already in repo) as an additional source.

from __future__ import annotations

import datetime as dt
import re
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from ned.entity_resolver import (
    load_company_entities,
    build_google_news_query,
    build_site_query,
    matches_entity,
    get_yahoo_symbol,
)
from ned.source_quality import split_publisher_suffix

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

_RSS_TIMEOUT = 15

# Load entity configurations once at module level
_ENTITIES = load_company_entities()


def _fetch_rss(url: str) -> list[dict]:
    """Fetch and parse an RSS/Atom feed. Returns list of item dicts."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=_RSS_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as exc:
        print(f"[ned/news] RSS fetch failed {url}: {exc}")
        return []

    items = []
    # RSS 2.0
    for item in root.findall(".//item"):
        pub_str = (item.findtext("pubDate") or "").strip()
        # Google News tags each item with the real publisher:
        #   <source url="https://www.kalkine.com.au">Kalkine Media</source>
        # Ned used to ignore it, which is why Kalkine could not be told apart.
        src_el = item.find("source")
        items.append({
            "publisher": (src_el.text or "").strip() if src_el is not None else "",
            "publisher_url": src_el.get("url", "") if src_el is not None else "",
            "title": (item.findtext("title") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
            "description": (item.findtext("description") or "")[:400].strip(),
            "published_str": pub_str,
            "published": _parse_date(pub_str),
        })
    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns):
        pub_str = (entry.findtext("atom:published", namespaces=ns) or "").strip()
        link_el = entry.find("atom:link", ns)
        items.append({
            "title": (entry.findtext("atom:title", namespaces=ns) or "").strip(),
            "link": link_el.get("href", "") if link_el is not None else "",
            "description": (entry.findtext("atom:summary", namespaces=ns) or "")[:400].strip(),
            "published_str": pub_str,
            "published": _parse_date(pub_str),
        })
    return items


def _parse_date(s: str) -> dt.datetime | None:
    """Best-effort parse of RSS/Atom date strings → UTC datetime."""
    if not s:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ):
        try:
            parsed = dt.datetime.strptime(s, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def _ticker_code_pattern(ticker: str) -> re.Pattern:
    """'ASX:BXB', 'ASX: BXB', '(ASX:BXB)', 'LSE:RR.' — how Market Index,
    Stockhead and most wraps write a code. Exchange prefix required so a bare
    three-letter code (CAT, IAG) never matches an ordinary word."""
    code = re.escape(ticker.rstrip(".").lower())
    return re.compile(rf"\b(?:asx|lse|nyse|nasdaq)\s*[:\-]\s*{code}(?![a-z0-9])")


def _matches_company(text: str, ticker: str, company_name: str) -> tuple[bool, str]:
    """
    Check if text matches a company using entity-based disambiguation.
    
    Returns:
        Tuple of (matches: bool, reason: str)
    """
    if _ticker_code_pattern(ticker).search(text.lower()):
        return True, f"ticker code ASX:{ticker}"

    entity = _ENTITIES.get(ticker)
    
    if entity:
        # Use entity-based matching for configured companies
        match, reason = matches_entity(text, entity)
        if match:
            print(f"[ned/news] {ticker} matched: {reason}")
        return match, reason
    else:
        # Fallback to basic matching for unconfigured companies
        # (Less strict, but maintains backward compatibility)
        haystack = text.lower()
        
        # Check for ticker match
        if re.search(rf"\b{re.escape(ticker.lower())}\b", haystack):
            print(f"[ned/news] {ticker} matched: ticker found")
            return True, "ticker found"
        
        # Check for first word of company name (if >3 chars)
        first_word = company_name.split()[0].lower()
        if len(first_word) > 3 and first_word in haystack:
            print(f"[ned/news] {ticker} matched: company name word '{first_word}'")
            return True, f"company name word '{first_word}'"
        
        return False, "no match"


def scan_rss_feeds(
    feed_configs: list[dict],
    companies: dict[str, str],   # {TICKER: "Company Name"}
    lookback_hours: int,
    seen_keys: set[str],
) -> list[dict]:
    """
    Scan configured RSS feeds for company mentions.
    Returns list of hit dicts.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=lookback_hours)
    hits: list[dict] = []

    for feed in feed_configs:
        feed_type = feed.get("type", "static")
        label = feed.get("label", feed["url"])

        if feed_type == "google_news_sites":
            # Same Google News RSS, restricted to the target sites. Pulls
            # headlines even from paywalled outlets (AFR, The Australian), which
            # is the point: "Brambles was mentioned on Livewire" is the signal.
            sites = feed.get("sites") or []
            if not sites:
                continue
            for ticker, name in companies.items():
                entity = _ENTITIES.get(ticker) or {"aliases": [name]}
                query = build_site_query(entity, ticker, sites)
                url = feed["url"].replace("{query}", query)
                for item in _fetch_rss(url):
                    text = f"{item['title']} {item['description']}"
                    matches, reason = _matches_company(text, ticker, name)
                    if matches:
                        _check_item(item, ticker, name, label, cutoff, seen_keys, hits,
                                    f"gnews|{ticker}|{item['link']}", feed)
            continue

        if feed_type == "google_news":
            # One RSS query per company using entity-driven queries
            for ticker, name in companies.items():
                entity = _ENTITIES.get(ticker)
                
                if entity:
                    # Build entity-driven query
                    query = build_google_news_query(entity)
                    print(f"[ned/news] Google News query for {ticker}: {urllib.parse.unquote_plus(query)}")
                else:
                    # Fallback to simple query for unconfigured companies
                    query = urllib.parse.quote_plus(f'"{name}"')
                    print(f"[ned/news] Google News query for {ticker} (fallback): {urllib.parse.unquote_plus(query)}")
                
                url = feed["url"].replace("{query}", query)
                items = _fetch_rss(url)
                
                # Apply second-pass validation to each item
                validated_count = 0
                rejected_count = 0
                
                for item in items:
                    text = f"{item['title']} {item['description']}".lower()
                    matches, reason = _matches_company(text, ticker, name)
                    
                    if matches:
                        _check_item(item, ticker, name, label, cutoff, seen_keys, hits, f"gnews|{ticker}|{item['link']}", feed)
                        validated_count += 1
                    else:
                        rejected_count += 1
                        print(f"[ned/news] {ticker} rejected: {reason} - {item['title'][:60]}")
                
                if validated_count > 0 or rejected_count > 0:
                    print(f"[ned/news] {ticker}: {validated_count} accepted, {rejected_count} rejected")
        else:
            # Static feed — fetch once, filter by company with validation
            items = _fetch_rss(feed["url"])
            for item in items:
                text = f"{item['title']} {item['description']}"
                for ticker, name in companies.items():
                    matches, reason = _matches_company(text, ticker, name)
                    if matches:
                        _check_item(item, ticker, name, label, cutoff, seen_keys, hits, f"rss|{ticker}|{item['link']}", feed)

    return hits


def _check_item(
    item: dict,
    ticker: str,
    company_name: str,
    label: str,
    cutoff: dt.datetime,
    seen_keys: set[str],
    hits: list[dict],
    key: str,
    feed: dict | None = None,
) -> None:
    pub = item.get("published")
    if pub and pub < cutoff:
        return
    if key in seen_keys:
        return
    feed_type = (feed or {}).get("type", "static")
    title, publisher = item["title"], item.get("publisher", "")
    if feed_type.startswith("google_news"):
        # Google News appends " - Publisher" to every title; strip it for
        # display and use it when the <source> tag is missing.
        title, suffix_pub = split_publisher_suffix(item["title"])
        publisher = publisher or suffix_pub
    elif not publisher:
        publisher = label   # a site's own feed: the feed IS the publisher
    hit = {
        "source": f"{label} ({publisher})" if publisher and publisher != label else label,
        "source_type": "rss",
        "publisher": publisher,
        "publisher_url": item.get("publisher_url", ""),
        "tickers": [ticker],
        "title": title,
        "url": item["link"],
        "description": item["description"],
        "published": pub.isoformat() if pub else "",
        "seen_key": key,
    }
    if feed and feed.get("tier") in (1, 2, 3):
        hit["tier_override"] = feed["tier"]
    hits.append(hit)


def scan_yahoo_finance(
    companies: dict[str, str],
    lookback_hours: int,
    seen_keys: set[str],
) -> list[dict]:
    """
    Pull Yahoo Finance news per ticker using the existing news_context_fetcher.
    Falls back gracefully if unavailable.
    """
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from news_context_fetcher import fetch_news_context
    except ImportError:
        return []

    cutoff_ts = (dt.datetime.utcnow() - dt.timedelta(hours=lookback_hours)).timestamp()
    hits: list[dict] = []

    for ticker, name in companies.items():
        # Use entity-specific Yahoo symbol if available
        entity = _ENTITIES.get(ticker)
        exchange_ticker = get_yahoo_symbol(ticker, entity)
        
        print(f"[ned/news] Yahoo Finance for {ticker}: using symbol {exchange_ticker}")
        
        items = fetch_news_context(exchange_ticker, max_items=5)
        
        validated_count = 0
        rejected_count = 0
        
        for item in items:
            pub_ts = item.get("published_at") or 0
            if pub_ts and pub_ts < cutoff_ts:
                continue
            
            # Apply second-pass validation
            text = f"{item.get('title', '')} {item.get('description', '')}".lower()
            matches, reason = _matches_company(text, ticker, name)
            
            if not matches:
                rejected_count += 1
                print(f"[ned/news] {ticker} (Yahoo) rejected: {reason} - {item.get('title', '')[:60]}")
                continue
            
            validated_count += 1
            key = f"yf|{ticker}|{item.get('link', '')}"
            if key in seen_keys:
                continue
            hits.append({
                "source": f"Yahoo Finance ({item.get('publisher', '?')})",
                "source_type": "yahoo",
                "publisher": item.get("publisher", ""),
                "tickers": [ticker],
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "description": "",
                "published": str(pub_ts),
                "seen_key": key,
            })
        
        if validated_count > 0 or rejected_count > 0:
            print(f"[ned/news] {ticker} (Yahoo): {validated_count} accepted, {rejected_count} rejected")

    return hits
