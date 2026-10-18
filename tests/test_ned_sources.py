"""Ned source tiers (Kalkine demotion), target-site search, and newsletters."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from ned import email_builder, newsletter_scanner as nls, source_quality as sq
from ned.importance_scorer import sort_by_importance
from ned.news_scanner import _matches_company, _check_item, _ticker_code_pattern
from ned.entity_resolver import build_site_query

REPO = Path(__file__).resolve().parent.parent
MEDIA = yaml.safe_load((REPO / "media_sources.yaml").read_text())
TIERS = sq.load_tiers(MEDIA)


def _hit(title, publisher="", url="", ticker="BXB", key=None, **kw):
    h = {"title": title, "publisher": publisher, "url": url or f"https://x/{title}",
         "source": "Google News", "tickers": [ticker], "seen_key": key or f"k|{title}|{publisher}"}
    h.update(kw)
    return h


# ---------- tiers ----------
def test_kalkine_is_tier3_from_publisher_or_link():
    assert sq.classify_tier(_hit("x", "Kalkine Media"), TIERS) == 3
    assert sq.classify_tier(_hit("x", "", url="https://kalkine.com.au/news/x"), TIERS) == 3


def test_quality_and_default_tiers():
    assert sq.classify_tier(_hit("x", "The Australian Financial Review", url="https://www.afr.com/a"), TIERS) == 1
    assert sq.classify_tier(_hit("x", "Livewire Markets"), TIERS) == 1
    assert sq.classify_tier(_hit("x", "Some Blog"), TIERS) == 2


def test_kalkine_stays_tier3_even_if_config_forgets_it():
    tiers = sq.load_tiers({"source_tiers": {"tier1": ["afr.com"], "tier3": []}})
    assert sq.classify_tier(_hit("x", "Kalkine Media"), tiers) == 3


def test_feed_tier_override_wins():
    assert sq.classify_tier(_hit("x", "Kalkine", tier_override=1), TIERS) == 1


def test_publisher_suffix_split():
    assert sq.split_publisher_suffix("Brambles lifts guidance - Kalkine Media") == (
        "Brambles lifts guidance", "Kalkine Media")
    assert sq.split_publisher_suffix("No suffix here") == ("No suffix here", "")


# ---------- scoring ----------
def test_kalkine_capped_low_and_ranked_below_real_story():
    kal = _hit("Aussie Broadband completes buy-back, revenue, results update", "Kalkine Media", tier=3)
    afr = _hit("Brambles CEO flags contract win", "AFR", tier=1)
    out = sort_by_importance([kal, afr])
    assert out[0] is afr
    assert kal["importance_level"] == "LOW"
    assert afr["importance_level"] in ("CRITICAL", "HIGH")


def test_not_material_is_demoted_not_dropped():
    h = _hit("Brambles full-year result", "Some Blog", tier=2, not_material=True)
    sort_by_importance([h])
    assert h["importance_level"] == "LOW"


# ---------- dedupe ----------
def test_same_story_collapses_to_best_tier_and_keeps_seen_keys():
    kal = _hit("Brambles lifts FY27 guidance on pallet pricing", "Kalkine Media", tier=3, key="k1")
    afr = _hit("Brambles lifts FY27 guidance as pallet pricing holds", "AFR", tier=1, key="k2")
    other = _hit("Brambles lifts FY27 guidance on pallet pricing", "Kalkine Media", ticker="CPU", tier=3, key="k3")
    out = sq.collapse_duplicates([kal, afr, other])
    assert len(out) == 2
    winner = next(h for h in out if h["tickers"] == ["BXB"])
    assert winner["publisher"] == "AFR"
    assert winner["also_covered_by"] == ["Kalkine Media"]
    assert "k1" in winner["merged_seen_keys"]


def test_same_url_merges_regardless_of_wording():
    a = _hit("One headline", "Pub A", url="https://same", tier=2, key="a")
    b = _hit("Totally different words", "Pub B", url="https://same", tier=2, key="b")
    assert len(sq.collapse_duplicates([a, b])) == 1


def test_rollup_counts_by_publisher():
    hits = [_hit("a", "Kalkine Media", tier=3), _hit("b", "Kalkine Media", tier=3),
            _hit("c", "Kalkine Media", ticker="DRO", tier=3), _hit("d", "AFR", tier=1)]
    assert sq.low_quality_rollup(hits) == [("Kalkine Media", [("BXB", 2), ("DRO", 1)])]


# ---------- matching / site search ----------
def test_ticker_code_pattern_needs_exchange_prefix():
    assert _ticker_code_pattern("BXB").search("brambles (asx:bxb) rose")
    assert _ticker_code_pattern("BXB").search("asx: bxb")
    assert not _ticker_code_pattern("CAT").search("the cat sat")
    assert not _ticker_code_pattern("CAT").search("asx:catx")
    assert _ticker_code_pattern("RR.").search("lse:rr shares")


def test_matches_company_on_ticker_code():
    ok, reason = _matches_company("Shares in ASX:PWH jumped", "PWH", "PWR Holdings Limited")
    assert ok and "ticker code" in reason


def test_site_query_shape():
    import urllib.parse
    q = urllib.parse.unquote_plus(build_site_query({"aliases": ["Brambles"]}, "BXB", ["afr.com", "livewiremarkets.com"]))
    assert q == '("Brambles" OR "ASX:BXB") (site:afr.com OR site:livewiremarkets.com)'


def test_check_item_reads_google_publisher_and_strips_suffix():
    hits = []
    item = {"title": "Brambles lifts guidance - Kalkine Media", "link": "https://g/1", "description": "",
            "published": None, "publisher": "Kalkine Media", "publisher_url": "https://kalkine.com.au"}
    _check_item(item, "BXB", "Brambles", "Google News", dt.datetime.now(dt.timezone.utc), set(), hits, "k",
                {"type": "google_news"})
    assert hits[0]["title"] == "Brambles lifts guidance"
    assert hits[0]["publisher"] == "Kalkine Media"
    assert sq.classify_tier(hits[0], TIERS) == 3


def test_static_feed_title_with_dash_is_not_stripped():
    hits = []
    item = {"title": "Brambles: buy - or sell?", "link": "https://f/1", "description": "", "published": None}
    _check_item(item, "BXB", "Brambles", "Motley Fool Australia", dt.datetime.now(dt.timezone.utc), set(), hits,
                "k", {"type": "static", "tier": 2})
    assert hits[0]["title"] == "Brambles: buy - or sell?"
    assert hits[0]["publisher"] == "Motley Fool Australia"
    assert hits[0]["tier_override"] == 2


# ---------- newsletters ----------
KESTREL_HTML = """<html><head><title>Kestrel brief 16 October 2026</title><style>x{}</style></head>
<body><nav>Home Briefs Subscribe</nav><h2>Top Line</h2>
<p>Army's UH-60M Black Hawks have completed their first overseas deployment, in Papua New Guinea.</p>
<h2>Market and industry moves</h2>
<p>DroneShield has won a new European counter-drone order worth $12 million, its largest this year.</p>
<p>archTIS signed a data-centric security deal with a Five Eyes agency, according to the company.</p>
</body></html>"""


class _Resp:
    def __init__(self, code, text=""):
        self.status_code, self.text = code, text


def _fake_get(url, headers=None, timeout=None):
    return _Resp(200, KESTREL_HTML) if url.endswith("2026-10-16") else _Resp(404)


KESTREL_CFG = next(n for n in MEDIA["newsletters"] if n["label"] == "Kestrel Run")
NOW = dt.datetime(2026, 10, 16, 23, 30, tzinfo=dt.timezone.utc)   # 17 Oct morning Sydney


def test_kestrel_configured():
    assert KESTREL_CFG["from"] == "brief@kestrelrun.com"
    assert "{date}" in KESTREL_CFG["web_archive"]


def test_archive_dates_cover_window_in_sydney_time():
    dates = nls._archive_dates(48, "Australia/Sydney", NOW)
    assert dates[0] == "2026-10-17" and "2026-10-16" in dates and "2026-10-15" in dates


def test_web_issue_fetched_and_matched(monkeypatch):
    monkeypatch.delenv("NED_IMAP_USER", raising=False)
    monkeypatch.delenv("NED_IMAP_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    monkeypatch.delenv("EMAIL_APP_PASSWORD", raising=False)
    run = nls.gather_issues([KESTREL_CFG], 48, get=_fake_get, now=NOW)
    # Inbox not configured is not an error: Kestrel has a web archive.
    assert run.status == "ok", run.error
    assert len(run.issues) == 1
    issue = run.issues[0]
    assert issue.link == "https://www.kestrelrun.com/briefs/2026-10-16"
    assert "Home Briefs" not in issue.text
    hits = nls.match_issue(issue, {"DRO": "DroneShield Limited", "AR9": "archTIS Limited",
                                   "BXB": "Brambles Limited"}, _matches_company, set())
    assert {h["tickers"][0] for h in hits} == {"DRO", "AR9"}
    dro = next(h for h in hits if h["tickers"] == ["DRO"])
    assert dro["title"].startswith("Kestrel Run: DroneShield has won")
    assert dro["tier_override"] == 1


def test_email_only_newsletter_without_inbox_is_flagged(monkeypatch):
    for k in ("NED_IMAP_USER", "NED_IMAP_PASSWORD", "EMAIL_FROM", "EMAIL_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    run = nls.gather_issues([{"label": "X", "from": "x@y.com"}], 48, get=_fake_get, now=NOW)
    assert run.status == "not_configured"


def test_admin_mail_is_skipped():
    assert nls._skip_subject("Confirm your Kestrel subscription", {})
    assert not nls._skip_subject("Friday brief: AUKUS undersea power", {})


def test_llm_digest_parses_and_filters_unknown_tickers():
    issue = nls.NewsletterIssue("Kestrel Run", "", "Brief", "id", None, "text", config=KESTREL_CFG)
    raw = ('```json\n{"summary": "Busy day.", "items": ['
           '{"tickers": ["DRO"], "headline": "Army counter-drone tender opens", "why": "DRO bids", "direct": false},'
           '{"tickers": ["EOS"], "headline": "Not held", "why": "x", "direct": true}]}\n```')
    out = nls.llm_digest_issue(issue, {"DRO": "DroneShield"}, lambda p: raw)
    assert out["status"] == "ok"
    assert [i["tickers"] for i in out["items"]] == [["DRO"]]


def test_llm_digest_failures_are_explicit():
    issue = nls.NewsletterIssue("K", "", "S", "id", None, "t", config={})
    assert nls.llm_digest_issue(issue, {}, lambda p: "not json")["status"] == "parse_error"

    def boom(p):
        raise RuntimeError("api down")
    assert nls.llm_digest_issue(issue, {}, boom)["status"] == "failed"


def test_prompt_marks_newsletter_untrusted():
    assert "untrusted" in nls.DIGEST_PROMPT


# ---------- email ----------
def test_email_rolls_up_kalkine_and_shows_newsletters():
    news = sort_by_importance([
        _hit("ABB completes buy-back", "Kalkine Media", ticker="ABB", tier=3),
        _hit("Brambles CEO on pallets", "AFR", tier=1, also_covered_by=["The Australian"]),
    ])
    nl = [{"label": "Kestrel Run", "subject": "Brief 16 Oct", "url": "https://k/1", "status": "ok",
           "summary": "AUKUS day.", "items": [{"tickers": ["DRO"], "headline": "Tender opens",
                                              "why": "DRO bids", "direct": False}], "error": ""}]
    plain, html = email_builder.build_email([], news, {}, 48, "2026-10-17", newsletters=nl,
                                            newsletter_status=("ok", ""))
    assert "WIRE REWRITES" in plain and "Kalkine Media: ABB (1)" in plain
    assert "NEWS & PRESS RELEASES" in plain
    news_section = plain.split("NEWS & PRESS RELEASES")[1].split("NEWSLETTERS")[0]
    assert "ABB completes buy-back" not in news_section
    assert "Also covered by The Australian" in html
    assert "Tender opens" in html and "(indirect)" in html
    for banned in ("display:flex", "display:grid", "<style", "class="):
        assert banned not in html


def test_email_shows_inbox_failure():
    plain, html = email_builder.build_email([], [], {}, 48, "d", newsletters=[],
                                            newsletter_status=("failed", "LOGIN failed"))
    assert "FAILED" in plain and "LOGIN failed" in html
