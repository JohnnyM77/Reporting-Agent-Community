"""Micky's Macro tests. No test hits a real API or a real IMAP server: the
model is a fake transport returning fixture JSON, and IMAP is a fake
connection object. Nothing here reads Johnny's real inbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from mickys_macro import (
    claim_extraction,
    company_mapping,
    config as mm_config,
    main as mm_main,
    portfolio_overlap,
    reports,
    scoring,
    store as mm_store,
    trend_mapping,
    wally_adapter,
)
from mickys_macro.schemas import (
    CompanyCandidate,
    EmailRecord,
    ExtractedClaim,
    InvestmentFilter,
    TrendDossier,
    ValuationSnapshot,
)
from shared import eodhd
from shared.llm import LLMResponse
from wally.config import STANDARD_WATCHLISTS

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Source registry: real addresses, never invented
# ---------------------------------------------------------------------------

def test_real_registry_loads_and_identifies_discovered_senders():
    registry = mm_config.load_source_registry()
    # Exact senders discovered in the real mailbox (see
    # docs/MICKYS_MACRO_ARCHITECTURE.md section 1.5) -- never invented.
    assert registry.identify_sender("citrini@substack.com") == "Citrini Research"
    assert registry.identify_sender("raydalio@substack.com") == "Ray Dalio / Economic Principles"
    assert registry.identify_sender("no-reply@principles.com") == "Ray Dalio / Economic Principles"
    assert registry.identify_sender("chamath@mail.beehiiv.com") == "Chamath Palihapitiya"
    # Plus-addressed sub-newsletters all resolve to the one source.
    assert registry.identify_sender("profgmedia+prof-g@substack.com") == "Scott Galloway (Prof G)"
    assert registry.identify_sender("profgmedia+no-mercy-no-malice@substack.com") == "Scott Galloway (Prof G)"


def test_registry_never_matches_unrelated_or_cross_promo_senders():
    registry = mm_config.load_source_registry()
    assert registry.identify_sender("no-reply@substack.com") is None
    assert registry.identify_sender("random.person@gmail.com") is None
    assert registry.is_excluded_subject("Scott Galloway, Sabrina Ramonov, and X posted new notes")
    assert not registry.is_excluded_subject("Macro Memo: Regime Change")


def test_registry_keyword_tagging_is_deterministic():
    registry = mm_config.load_source_registry()
    cats = registry.keywords_for("Copper demand from electrification is outstripping mine supply")
    assert "ELECTRIFICATION_METALS" in cats


# ---------------------------------------------------------------------------
# Store: idempotent dedup, refuses a tracked path
# ---------------------------------------------------------------------------

def test_store_dedup_is_idempotent(tmp_path):
    store = mm_store.Store(tmp_path / "data")
    assert not store.seen_message("msg-1")
    store.mark_message_seen("msg-1", "2026-10-18T00:00:00Z")
    assert store.seen_message("msg-1")
    # Re-marking (a re-run) does not raise or duplicate.
    store.mark_message_seen("msg-1", "2026-10-18T00:00:00Z")
    assert store.seen_message("msg-1")


def test_store_refuses_a_tracked_path_inside_the_public_repo():
    with pytest.raises(mm_store.StoreConfigError):
        mm_store._assert_not_tracked(REPO_ROOT / "mickys_macro", REPO_ROOT)


def test_store_accepts_the_gitignored_data_dir():
    # mickys_macro_data/ is listed in .gitignore -- see that file.
    mm_store._assert_not_tracked(REPO_ROOT / "mickys_macro_data", REPO_ROOT)


# ---------------------------------------------------------------------------
# Claim extraction: JSON parsing, truncation stays a parse_error, email
# content is framed as untrusted
# ---------------------------------------------------------------------------

def _email(text: str = "Some research body.") -> EmailRecord:
    return EmailRecord(
        message_id="<abc@substack.com>",
        source_name="Citrini Research",
        sender="citrini@substack.com",
        subject="Test issue",
        received_at="2026-10-18T00:00:00Z",
        raw_text=text,
    )


def test_claim_extraction_parses_clean_json(monkeypatch):
    payload = {
        "claims": [
            {
                "claim_type": "FORECAST",
                "text": "Grid capex will double this decade.",
                "companies": ["Nvidia"],
                "industries": ["power"],
                "commodities": [],
                "countries": ["US"],
                "technologies": ["AI data centres"],
                "time_horizon": "10 years",
                "supporting_evidence": "cited utility capex plans",
                "counter_evidence": "",
                "confidence": "MEDIUM",
                "taxonomy_categories": ["ELECTRICITY_GRID"],
            }
        ]
    }
    monkeypatch.setattr(
        claim_extraction, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(payload), stop_reason="end_turn", input_tokens=10, output_tokens=10),
    )
    cfg = mm_config.RunConfig.from_env({})
    result = claim_extraction.extract_claims(object(), _email(), ["ELECTRICITY_GRID"], cfg)
    assert result.status == "ok"
    assert len(result.claims) == 1
    assert result.claims[0].claim_type == "FORECAST"
    assert result.claims[0].companies == ["Nvidia"]


def test_claim_extraction_truncation_never_bracket_closed(monkeypatch):
    # Cut off mid-string: a bracket-closing repair would silently turn this
    # into a plausible-looking claim. It must stay a parse_error instead.
    truncated_text = '{"claims": [{"claim_type": "FACT", "text": "partial sent'
    monkeypatch.setattr(
        claim_extraction, "send",
        lambda *a, **k: LLMResponse(text=truncated_text, stop_reason="max_tokens", input_tokens=10, output_tokens=10),
    )
    cfg = mm_config.RunConfig.from_env({})
    result = claim_extraction.extract_claims(object(), _email(), ["ELECTRICITY_GRID"], cfg)
    assert result.status == "parse_error"
    assert result.truncated


def test_claim_extraction_handles_api_failure(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(claim_extraction, "send", _raise)
    cfg = mm_config.RunConfig.from_env({})
    result = claim_extraction.extract_claims(object(), _email(), ["ELECTRICITY_GRID"], cfg)
    assert result.status == "failed"


def test_claim_extraction_prompt_frames_email_body_as_untrusted():
    assert "untrusted" in claim_extraction.SYSTEM_PROMPT.lower()
    assert "ignore all" in claim_extraction.SYSTEM_PROMPT.lower()


def test_claim_extraction_empty_claims_is_still_ok(monkeypatch):
    monkeypatch.setattr(
        claim_extraction, "send",
        lambda *a, **k: LLMResponse(text='{"claims": []}', stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )
    cfg = mm_config.RunConfig.from_env({})
    result = claim_extraction.extract_claims(object(), _email(), [], cfg)
    assert result.status == "ok"
    assert result.claims == []


# ---------------------------------------------------------------------------
# Trend mapping: deterministic grouping + dossier id stability
# ---------------------------------------------------------------------------

def _claim(**kw) -> ExtractedClaim:
    base = dict(
        email_id="email-1", source_name="Citrini Research", claim_type="FORECAST",
        text="x", taxonomy_categories=["ELECTRICITY_GRID"],
    )
    base.update(kw)
    return ExtractedClaim(**base)


def test_group_by_category_is_deterministic():
    claims = [_claim(taxonomy_categories=["ELECTRICITY_GRID"]), _claim(taxonomy_categories=["SEMICONDUCTORS_COMPUTE"])]
    grouped = trend_mapping.group_by_category(claims)
    assert set(grouped) == {"ELECTRICITY_GRID", "SEMICONDUCTORS_COMPUTE"}


def test_dossier_id_is_stable_across_runs():
    cat = mm_config.TaxonomyCategory(id="ELECTRICITY_GRID", label="Electricity demand")
    claims = [_claim()]
    assert trend_mapping.dossier_id_for(cat, claims) == trend_mapping.dossier_id_for(cat, claims)
    assert trend_mapping.dossier_id_for(cat, claims) == "dossier_electricity_grid"


def test_synthesize_dossier_parses_and_never_upgrades_inference(monkeypatch):
    payload = {
        "name": "Grid build-out",
        "thesis": "Utilities are under-building for AI load growth.",
        "what_changing_and_why": "...",
        "expected_duration": "10-15 years",
        "adoption_curve": "early",
        "demand_drivers": ["data centre load growth"],
        "supply_constraints": ["transformer lead times"],
        "capex_and_financing": "utility rate cases",
        "policy_and_geopolitics": [],
        "winners": ["GE Vernova"],
        "losers": [],
        "disrupted_business_models": [],
        "first_order_consequences": [],
        "second_order_consequences": [],
        "third_order_consequences": [],
        "evidence_for": ["utility capex guidance up"],
        "evidence_against": [],
        "invalidation_criteria": ["demand growth stalls"],
        "leading_indicators": ["transformer order backlogs"],
        "secular_or_cyclical": "SECULAR",
        "confidence": "MEDIUM",
    }
    monkeypatch.setattr(
        trend_mapping, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(payload), stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )
    cat = mm_config.TaxonomyCategory(id="ELECTRICITY_GRID", label="Electricity demand")
    cfg = mm_config.RunConfig.from_env({})
    result = trend_mapping.synthesize_dossier(object(), cat, [_claim(companies=["GE Vernova"])], None, cfg)
    assert result.status == "ok"
    assert result.dossier.secular_or_cyclical == "SECULAR"
    assert "GE VERNOVA" in result.dossier.linked_companies  # linked_companies is normalised upper-case
    assert result.dossier.id == "dossier_electricity_grid"


# ---------------------------------------------------------------------------
# Scoring: ten independent dimensions, never a combined score
# ---------------------------------------------------------------------------

def test_scoring_never_exposes_a_combined_score(monkeypatch):
    dims = {
        d: {"score": 7, "rationale": "r", "evidence_refs": [], "uncertainty": "u"}
        for d in scoring.DIMENSIONS
    }
    monkeypatch.setattr(
        scoring, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(dims), stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )
    dossier = TrendDossier(id="dossier_x", category="ELECTRICITY_GRID", name="Grid")
    cfg = mm_config.RunConfig.from_env({})
    result = scoring.score_dossier(object(), dossier, cfg)
    assert result.status == "ok"
    score_fields = set(result.score.model_dump(mode="json")) - {"id", "dossier_id", "created_at"}
    assert score_fields == set(scoring.DIMENSIONS)
    # No field anywhere named like a combined/overall score.
    assert not any("overall" in f or "combined" in f for f in score_fields)


# ---------------------------------------------------------------------------
# Investment filter stays four separate conclusions, never one flag
# ---------------------------------------------------------------------------

def test_investment_filter_keeps_four_conclusions_separate():
    filt = InvestmentFilter(
        macro_attractiveness="strong",
        industry_economics="attractive",
        company_quality="high",
        valuation_and_prospective_return="expensive -- consensus has caught up",
        portfolio_suitability="would concentrate existing AI exposure",
    )
    fields = set(filt.model_dump(mode="json"))
    assert fields == {
        "macro_attractiveness", "industry_economics", "company_quality",
        "valuation_and_prospective_return", "portfolio_suitability", "further_work_needed",
    }
    # Growing industry + high quality does not collapse into a single verdict field.
    assert not hasattr(filt, "is_attractive_investment")
    assert not hasattr(filt, "verdict")


# ---------------------------------------------------------------------------
# Company mapping: resolves a ticker from a company name, never states a
# live multiple as fact
# ---------------------------------------------------------------------------

def test_company_mapping_prompt_forbids_stating_live_multiples_as_fact():
    assert "do not state a specific share price" in company_mapping.SYSTEM_PROMPT.lower()


def test_build_candidate_resolves_ticker_from_company_name(monkeypatch):
    payload = {
        "ticker": "NVDA",
        "exchange": "NASDAQ",
        "currency": "USD",
        "name": "Nvidia Corporation",
        "exposure_type": "DIRECT_BENEFICIARY",
        "causal_chain": ["MACRO CHANGE: AI compute demand", "CASH FLOW AND EARNINGS: data centre GPU revenue"],
        "competitive_advantage": "CUDA ecosystem lock-in",
        "key_risks": ["customer concentration"],
        "why_now": "hyperscaler capex guidance still rising",
        "investment_filter": {
            "macro_attractiveness": "strong",
            "industry_economics": "attractive",
            "company_quality": "high",
            "valuation_and_prospective_return": "qualitatively expensive -- see sourced multiples",
            "portfolio_suitability": "would add concentrated AI exposure",
            "further_work_needed": ["check customer concentration in the 10-K"],
        },
    }
    monkeypatch.setattr(
        company_mapping, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(payload), stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )
    for name in eodhd.TOKEN_ENV:
        monkeypatch.delenv(name, raising=False)
    eodhd.clear_cache()
    dossier = TrendDossier(id="dossier_x", category="SEMICONDUCTORS_COMPUTE", name="AI compute")
    cfg = mm_config.RunConfig.from_env({})
    result = company_mapping.build_candidate(object(), "Nvidia", dossier, [], cfg)
    assert result.status == "ok"
    assert result.candidate.ticker == "NVDA"
    assert result.candidate.exposure_type == "DIRECT_BENEFICIARY"
    # No live EODHD token in this test -- valuation must not be invented.
    assert result.candidate.valuation.not_covered_reason


# ---------------------------------------------------------------------------
# Valuation is never fabricated -- a coverage gap renders as such
# ---------------------------------------------------------------------------

def test_valuation_not_fabricated_when_eodhd_has_no_token(monkeypatch):
    for name in eodhd.TOKEN_ENV:
        monkeypatch.delenv(name, raising=False)
    eodhd.clear_cache()
    snap = company_mapping.resolve_valuation("NHC", "ASX")
    assert snap.pe is None
    assert snap.price is None
    assert snap.not_covered_reason  # explicitly labelled, never guessed


def test_valuation_not_fabricated_for_an_uncovered_exchange(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "fake-token-for-test")
    eodhd.clear_cache()
    # SGX is explicitly not on the EODHD plan (shared/eodhd.py::symbol).
    snap = company_mapping.resolve_valuation("D05", "SGX")
    assert snap.not_covered_reason
    assert snap.pe is None


# ---------------------------------------------------------------------------
# Portfolio overlap: read-only, never writes tickers.yaml/watchlists
# ---------------------------------------------------------------------------

def test_overlap_is_read_only_and_finds_a_held_ticker(tmp_path, monkeypatch):
    (tmp_path / "watchlists").mkdir()
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "tickers.yaml").write_text(
        yaml.safe_dump({"asx": {"NHC": "New Hope Corporation Limited"}, "etf_tickers": []}),
        encoding="utf-8",
    )
    before = (tmp_path / "tickers.yaml").read_text(encoding="utf-8")
    tags = portfolio_overlap.overlap_for("NHC", repo_root=tmp_path)
    after = (tmp_path / "tickers.yaml").read_text(encoding="utf-8")
    assert after == before  # never modified
    assert any("already held" in t for t in tags)


def test_overlap_finds_nothing_for_an_unrelated_ticker(tmp_path):
    (tmp_path / "watchlists").mkdir()
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "tickers.yaml").write_text(yaml.safe_dump({"asx": {}, "etf_tickers": []}), encoding="utf-8")
    assert portfolio_overlap.overlap_for("ZZZ", repo_root=tmp_path) == []


# ---------------------------------------------------------------------------
# Wally hand-off: a proposal file, never merged into what Wally screens
# ---------------------------------------------------------------------------

def test_wally_proposal_is_not_in_standard_watchlists():
    rels = {Path(p).name for p in STANDARD_WATCHLISTS}
    assert wally_adapter.PROPOSAL_PATH.name not in rels


def test_wally_proposal_file_matches_watchlist_loader_schema(tmp_path):
    candidate = CompanyCandidate(
        dossier_id="dossier_electricity_grid", ticker="NVDA", exchange="NASDAQ",
        exposure_type="DIRECT_BENEFICIARY", why_now="AI data centre buildout",
    )
    out = tmp_path / "macro_candidates_proposed.yaml"
    n = wally_adapter.write_proposal([candidate], path=out)
    assert n == 1
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["tickers"] == ["NVDA"]
    assert "NVDA" in data["candidate_notes"]


def test_wally_proposal_is_idempotent_no_duplicate_tickers(tmp_path):
    candidates = [
        CompanyCandidate(dossier_id="d1", ticker="NVDA", exposure_type="DIRECT_BENEFICIARY"),
        CompanyCandidate(dossier_id="d2", ticker="NVDA", exposure_type="DIRECT_BENEFICIARY"),
    ]
    out = tmp_path / "macro_candidates_proposed.yaml"
    n = wally_adapter.write_proposal(candidates, path=out)
    assert n == 1


# ---------------------------------------------------------------------------
# Email HTML: table-only, inline styles, same hard rule every agent follows
# ---------------------------------------------------------------------------

def _assert_email_safe_html(html_body: str) -> None:
    assert "display:flex" not in html_body
    assert "display:grid" not in html_body
    assert "<style" not in html_body
    assert "class=" not in html_body


def test_daily_brief_html_is_email_safe():
    inp = reports.DailyBriefInputs(
        run_date="2026-10-18", new_claims=[], updated_dossiers=[], new_candidates=[],
        contradicting_evidence=[], portfolio_notes=[], next_indicators=[],
        emails_processed=3, emails_skipped_duplicate=1,
    )
    _, _, html_body = reports.build_daily_brief(inp)
    _assert_email_safe_html(html_body)


def test_daily_brief_with_content_is_email_safe():
    dossier = TrendDossier(id="d1", category="ELECTRICITY_GRID", name="Grid", what_changing_and_why="x" * 10)
    candidate = CompanyCandidate(dossier_id="d1", ticker="NVDA", exposure_type="DIRECT_BENEFICIARY", why_now="y")
    inp = reports.DailyBriefInputs(
        run_date="2026-10-18", new_claims=[], updated_dossiers=[dossier], new_candidates=[candidate],
        contradicting_evidence=["Grid: demand growth stalling"], portfolio_notes=["NVDA: already held"],
        next_indicators=["transformer backlog"], emails_processed=3, emails_skipped_duplicate=1,
    )
    _, _, html_body = reports.build_daily_brief(inp)
    _assert_email_safe_html(html_body)
    assert "NVDA" in html_body


def test_weekly_review_html_is_email_safe():
    dossier = TrendDossier(id="d1", category="ELECTRICITY_GRID", name="Grid")
    inp = reports.WeeklyReviewInputs(
        week_ending="2026-10-18", ranked=[(dossier, None)], conviction_changes=[], new_bottlenecks=[],
        improving_companies=[], deteriorating_companies=[], valuation_concerns=[],
        portfolio_cross_check=[], next_to_investigate=[], strongest_counterarguments=[],
    )
    _, _, html_body = reports.build_weekly_review(inp)
    _assert_email_safe_html(html_body)


def test_company_opportunity_brief_html_is_email_safe():
    dossier = TrendDossier(id="d1", category="ELECTRICITY_GRID", name="Grid", thesis="thesis text")
    candidate = CompanyCandidate(
        dossier_id="d1", ticker="NVDA", exchange="NASDAQ", exposure_type="DIRECT_BENEFICIARY",
        why_now="y", valuation=ValuationSnapshot(not_covered_reason="not covered"),
    )
    _, _, html_body = reports.build_company_opportunity_brief(candidate, dossier)
    _assert_email_safe_html(html_body)
    assert "not covered" in html_body


def test_gmail_digest_html_is_email_safe():
    emails = [_email()]
    _, _, html_body = reports.build_gmail_digest(emails, {})
    _assert_email_safe_html(html_body)


# ---------------------------------------------------------------------------
# Processing status discipline: a half-broken run must never look clean
# ---------------------------------------------------------------------------

def test_processing_statuses_match_the_established_vocabulary():
    from mickys_macro.schemas import ProcessingLog

    for status in ("OK", "SKIPPED_CAP", "FAILED_API", "FAILED_INVALID"):
        ProcessingLog(email_id="e1", status=status)


# ---------------------------------------------------------------------------
# A claim extracted but orphaned by the per-run call cap (e.g. a big
# backfill that spends the whole MAX_LLM_CALLS budget on extraction alone,
# as the first live run on 2026-10-18 actually did) must still get
# dossiered on a later run, not sit in the store forever uncounted.
# ---------------------------------------------------------------------------

def test_orphaned_claim_from_a_prior_run_still_gets_dossiered(tmp_path, monkeypatch):
    from mickys_macro import gmail_ingest as mm_gmail_ingest

    store = mm_store.Store(tmp_path / "data")
    # Simulates last run: the email was ingested and marked seen, its claim
    # was extracted and stored, but the call cap hit before trend mapping ran.
    orphaned = _claim(email_id="email-prior", taxonomy_categories=["ELECTRICITY_GRID"], dossiered=False)
    store.put("claim", orphaned)
    store.mark_message_seen("<prior@substack.com>", "2026-10-17T00:00:00Z")

    monkeypatch.setattr(mm_main.gmail_ingest, "fetch_emails",
                         lambda *a, **k: mm_gmail_ingest.IngestRun(status="ok", emails=[]))
    monkeypatch.setattr(mm_main, "make_client", lambda: object())
    # Isolate real-repo side effects the orchestrator normally writes --
    # the proposal watchlist and the public dashboard JSON -- so this test
    # never touches tracked files (see CLAUDE.md: "the test suite leaves
    # the working tree alone").
    monkeypatch.setattr(mm_main.wally_adapter, "write_proposal", lambda *a, **k: 0)
    monkeypatch.setattr(mm_main.web, "write_dashboard_json", lambda *a, **k: {})
    dossier_payload = {
        "name": "Grid build-out", "thesis": "x", "what_changing_and_why": "", "expected_duration": "",
        "adoption_curve": "", "demand_drivers": [], "supply_constraints": [], "capex_and_financing": "",
        "policy_and_geopolitics": [], "winners": [], "losers": [], "disrupted_business_models": [],
        "first_order_consequences": [], "second_order_consequences": [], "third_order_consequences": [],
        "evidence_for": [], "evidence_against": [], "invalidation_criteria": [], "leading_indicators": [],
        "secular_or_cyclical": "SECULAR", "confidence": "MEDIUM",
    }
    monkeypatch.setattr(
        mm_main.trend_mapping, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(dossier_payload), stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )

    summary = mm_main.run(mode="daily", send=False, store=store)

    assert summary["updated_dossiers"] == ["dossier_electricity_grid"]
    refreshed = store.get("claim", ExtractedClaim, orphaned.id)
    assert refreshed.dossiered is True


# ---------------------------------------------------------------------------
# An email skipped by the per-run call cap must stay unseen (retried next
# run), and the historical backfill window must not narrow to a 2-day
# incremental lookback until a run actually exhausts it. Both were real
# bugs the first live run (2026-10-18) hit: it fetched 40 emails, call-cap
# skipped 15 of them with no extraction attempt, and would have silently
# abandoned the rest of a year's backfill on the very next run.
# ---------------------------------------------------------------------------

def test_capped_email_is_not_marked_seen(tmp_path, monkeypatch):
    store = mm_store.Store(tmp_path / "data")
    email = _email_record("<capped@substack.com>")

    monkeypatch.setattr(mm_main.gmail_ingest, "fetch_emails",
                         lambda *a, **k: _fake_ingest_run([email]))
    monkeypatch.setattr(mm_main, "make_client", lambda: object())
    monkeypatch.setattr(mm_main.wally_adapter, "write_proposal", lambda *a, **k: 0)
    monkeypatch.setattr(mm_main.web, "write_dashboard_json", lambda *a, **k: {})
    # No ANTHROPIC_API_KEY-driven None here -- force the budget to zero so
    # every email hits the MAX_LLM_CALLS branch, not the missing-key one.
    monkeypatch.setenv("MICKYS_MACRO_MAX_LLM_CALLS", "0")

    mm_main.run(mode="daily", send=False, store=store)

    assert store.seen_message(email.message_id) is False


def test_backfill_not_marked_done_until_the_window_is_exhausted(tmp_path, monkeypatch):
    store = mm_store.Store(tmp_path / "data")
    # Simulates hitting max_emails_per_run: the fetch returns exactly the
    # cap's worth of emails, meaning there's very likely more still unfetched.
    emails = [_email_record(f"<e{i}@substack.com>") for i in range(3)]

    monkeypatch.setattr(mm_main.gmail_ingest, "fetch_emails",
                         lambda *a, **k: _fake_ingest_run(emails))
    monkeypatch.setattr(mm_main, "make_client", lambda: object())
    monkeypatch.setattr(mm_main.wally_adapter, "write_proposal", lambda *a, **k: 0)
    monkeypatch.setattr(mm_main.web, "write_dashboard_json", lambda *a, **k: {})
    monkeypatch.setenv("MICKYS_MACRO_MAX_EMAILS_PER_RUN", "3")
    monkeypatch.setenv("MICKYS_MACRO_MAX_LLM_CALLS", "0")

    mm_main.run(mode="daily", send=False, store=store)

    assert store.kv_get("backfill_done") is not True


def test_extraction_never_spends_the_whole_budget_leaving_none_for_mapping(tmp_path, monkeypatch):
    # The live 2026-10-18 backfill run fetched 40 new emails against a
    # MAX_LLM_CALLS=25 budget: extraction alone used all 25 calls and
    # updated_dossiers/new_candidates both came back empty even though
    # claims were extracted with real taxonomy categories. A reserve must
    # keep at least one call free for trend mapping whenever there are
    # more new emails than the extraction budget can cover.
    store = mm_store.Store(tmp_path / "data")
    emails = [_email_record(f"<e{i}@substack.com>") for i in range(5)]

    monkeypatch.setattr(mm_main.gmail_ingest, "fetch_emails",
                         lambda *a, **k: _fake_ingest_run(emails))
    monkeypatch.setattr(mm_main, "make_client", lambda: object())
    monkeypatch.setattr(mm_main.wally_adapter, "write_proposal", lambda *a, **k: 0)
    monkeypatch.setattr(mm_main.web, "write_dashboard_json", lambda *a, **k: {})
    monkeypatch.setenv("MICKYS_MACRO_MAX_LLM_CALLS", "5")
    monkeypatch.setenv("MICKYS_MACRO_RESERVE_CALLS_FOR_MAPPING", "2")

    claim_payload = {
        "claims": [{
            "claim_type": "FORECAST", "text": "Grid capex will double this decade.",
            "companies": [], "industries": [], "commodities": [], "countries": [],
            "technologies": [], "time_horizon": "", "supporting_evidence": "", "counter_evidence": "",
            "confidence": "MEDIUM", "taxonomy_categories": ["ELECTRICITY_GRID"],
        }]
    }
    monkeypatch.setattr(
        claim_extraction, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(claim_payload), stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )
    dossier_payload = {
        "name": "Grid build-out", "thesis": "x", "what_changing_and_why": "", "expected_duration": "",
        "adoption_curve": "", "demand_drivers": [], "supply_constraints": [], "capex_and_financing": "",
        "policy_and_geopolitics": [], "winners": [], "losers": [], "disrupted_business_models": [],
        "first_order_consequences": [], "second_order_consequences": [], "third_order_consequences": [],
        "evidence_for": [], "evidence_against": [], "invalidation_criteria": [], "leading_indicators": [],
        "secular_or_cyclical": "SECULAR", "confidence": "MEDIUM",
    }
    monkeypatch.setattr(
        mm_main.trend_mapping, "send",
        lambda *a, **k: LLMResponse(text=json.dumps(dossier_payload), stop_reason="end_turn", input_tokens=5, output_tokens=5),
    )

    summary = mm_main.run(mode="daily", send=False, store=store)

    assert summary["calls_made"] <= 5
    assert summary["updated_dossiers"] == ["dossier_electricity_grid"]
    # Only 3 of the 5 emails fit the reserved extraction budget (5 - 2); the
    # other 2 must be left unseen so they're retried next run.
    assert sum(1 for e in emails if store.seen_message(e.message_id)) == 3


def _email_record(message_id: str) -> EmailRecord:
    return EmailRecord(
        message_id=message_id, source_name="Citrini Research", sender="citrini@substack.com",
        subject="Test", received_at="2026-10-18T00:00:00Z", raw_text="body",
    )


def _fake_ingest_run(emails: list[EmailRecord]):
    from mickys_macro import gmail_ingest as mm_gmail_ingest

    return mm_gmail_ingest.IngestRun(status="ok", emails=emails)
