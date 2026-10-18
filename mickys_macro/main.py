"""Orchestrator for Micky's Macro. Idempotent: re-running never creates a
duplicate email record (dedup on Gmail Message-ID via the store), never
creates a duplicate dossier for the same taxonomy category (deterministic
id), and a company candidate is only built once per dossier+ticker.

Modes:
    incremental   -- short lookback window, the normal scheduled run
    backfill      -- long lookback window, run once to build the archive
    daily         -- incremental ingestion + send the Daily Macro Brief
    weekly        -- incremental ingestion + score dossiers + send the
                      Weekly Macro Investment Review
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from shared.email_service import send_email
from shared.llm import LLMConfigError, make_client

from . import company_mapping, gmail_ingest, pdf_render, reports, scoring, trend_mapping, wally_adapter, web
from .claim_extraction import extract_claims
from .config import RunConfig, load_source_registry, load_taxonomy
from .portfolio_overlap import overlap_for
from .schemas import CompanyCandidate, ExtractedClaim, ProcessingLog, TrendDossier
from .store import Store, open_store

log = logging.getLogger("mickys_macro")


def _today() -> str:
    return dt.date.today().isoformat()


def _build_pdf(kind: str, html: str, store: Store, slug: str) -> Path | None:
    """Render *html* to a PDF under the store (gitignored, not the public
    repo) and return its path, or None if weasyprint isn't installed --
    the email still sends without the attachment, same as Harry's
    runner.py degrades when weasyprint is missing on a runner."""
    path = store.root / "pdf" / f"{kind}_{slug}.pdf"
    try:
        return pdf_render.render_pdf(html, path)
    except ImportError:
        log.warning("[mickys_macro] weasyprint is not installed -- sending without the PDF attachment")
        return None
    except Exception as exc:  # noqa: BLE001 -- a PDF render failure must not block the email
        log.warning("[mickys_macro] PDF render failed (%s) -- sending without the attachment", exc)
        return None


def run(mode: str = "daily", *, send: bool = True, store: Store | None = None) -> dict:
    cfg = RunConfig.from_env()
    registry = load_source_registry()
    taxonomy = load_taxonomy()
    store = store or open_store()

    calls_made = [0]  # mutable cell so helpers below can increment it

    def budget_left() -> bool:
        return calls_made[0] < cfg.max_llm_calls

    # Claim extraction (step 2) is capped below the full budget so a large
    # backlog of new emails can never spend every call on extraction alone,
    # leaving trend mapping/company mapping/scoring (steps 3-5) with nothing
    # -- exactly what happened on the live 2026-10-18 backfill run (25/25
    # calls on extraction, zero dossiers). The reserved slice is always
    # available to the later steps, which still check against the full
    # budget_left() so they can also use whatever extraction didn't need.
    extraction_call_cap = max(0, cfg.max_llm_calls - cfg.reserve_calls_for_mapping)

    def extraction_budget_left() -> bool:
        return calls_made[0] < extraction_call_cap

    # -- 1. ingest -----------------------------------------------------------
    backfilled = bool(store.kv_get("backfill_done"))
    if mode == "backfill" or not backfilled:
        since = dt.date.today() - dt.timedelta(days=cfg.backfill_days)
    else:
        since = dt.date.today() - dt.timedelta(days=cfg.incremental_lookback_days)

    ingest = gmail_ingest.fetch_emails(registry, cfg, since=since, already_seen=store.seen_message)
    summary: dict = {
        "run_date": _today(),
        "mode": mode,
        "ingest_status": ingest.status,
        "ingest_error": ingest.error,
        "emails_processed": 0,
        "emails_skipped_duplicate": ingest.skipped_duplicate,
        "emails_skipped_excluded": ingest.skipped_excluded,
    }
    if ingest.status != "ok" and ingest.status != "not_configured":
        log.error("[mickys_macro] ingestion failed: %s", ingest.error)
    if ingest.status == "not_configured":
        log.warning("[mickys_macro] Gmail not configured: %s", ingest.error)

    new_emails = ingest.emails
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    for e in new_emails:
        store.put("email_record", e)
    # backfill_done only flips once a backfill run genuinely exhausts the
    # window (fetched fewer than the per-run cap) -- not just because one
    # run happened. The first live run (2026-10-18) hit max_emails_per_run
    # with a full year of history still unfetched across four senders; if
    # backfill_done had flipped there, every later run would have narrowed
    # straight to a 2-day incremental window and silently abandoned the
    # rest of that year's archive. Message-ID dedup (seen_message, set
    # just before each email is actually attempted below) means re-running
    # the same wide window costs nothing for emails already ingested.
    if ingest.status == "ok" and (mode == "backfill" or not backfilled) and len(new_emails) < cfg.max_emails_per_run:
        store.kv_set("backfill_done", True)
    summary["emails_processed"] = len(new_emails)

    # -- 2. claim extraction (one call per new email) -------------------------
    # Built unconditionally (not gated on new_emails): orphaned claims from a
    # prior run that hit the call cap before trend mapping ran still need a
    # client for dossier synthesis in step 3, even on a run that ingests
    # nothing new.
    client = None
    try:
        client = make_client()
    except LLMConfigError as exc:
        log.warning("[mickys_macro] %s -- no LLM calls will be made this run", exc)

    claims_by_email: dict[str, list[ExtractedClaim]] = {}
    all_new_claims: list[ExtractedClaim] = []
    category_ids = [c.id for c in taxonomy]
    for e in new_emails:
        # Marked seen only once we actually attempt extraction -- not here.
        # An email skipped for SKIPPED_CAP (no key, or this run's budget
        # exhausted) must stay unseen so gmail_ingest fetches it again next
        # run; the first live run marked all 40 fetched emails seen up
        # front, so the 15 that never got a call were lost for good even
        # though their content was never actually looked at.
        if client is None:
            store.put("processing_log", ProcessingLog(email_id=e.id, status="SKIPPED_CAP",
                                                        detail="ANTHROPIC_API_KEY not set"))
            continue
        if not extraction_budget_left():
            store.put("processing_log", ProcessingLog(email_id=e.id, status="SKIPPED_CAP",
                                                        detail="extraction call budget reached this run "
                                                               f"({extraction_call_cap} calls reserved "
                                                               f"{cfg.reserve_calls_for_mapping} for mapping)"))
            continue
        store.mark_message_seen(e.message_id, now_iso)
        result = extract_claims(client, e, category_ids, cfg)
        calls_made[0] += 1
        status = {"ok": "OK", "failed": "FAILED_API", "parse_error": "FAILED_INVALID"}.get(result.status, "FAILED_API")
        store.put("processing_log", ProcessingLog(email_id=e.id, status=status, detail=result.detail))
        if result.status == "ok" and result.claims:
            for c in result.claims:
                store.put("claim", c)
            claims_by_email[e.id] = result.claims
            all_new_claims.extend(result.claims)

    # -- 3. trend mapping (one call per touched category) ---------------------
    # Pulls every claim not yet folded into a dossier -- not just this run's
    # new_emails -- so a claim extracted under budget but orphaned by the
    # MAX_LLM_CALLS cap (e.g. a big backfill that spends the whole budget on
    # extraction alone) still gets dossiered on a later run instead of sitting
    # in the store forever uncounted.
    updated_dossiers: list[TrendDossier] = []
    pending_claims = [c for c in store.all("claim", ExtractedClaim) if not c.dossiered]
    grouped = trend_mapping.group_by_category(pending_claims)
    by_id = {c.id: c for c in taxonomy}
    for cat_id, claims in grouped.items():
        category = by_id.get(cat_id)
        if category is None or client is None or not budget_left():
            continue
        dossier_id = trend_mapping.dossier_id_for(category, claims)
        existing = store.get("trend_dossier", TrendDossier, dossier_id)
        result = trend_mapping.synthesize_dossier(client, category, claims, existing, cfg)
        calls_made[0] += 1
        if result.status == "ok" and result.dossier:
            store.put("trend_dossier", result.dossier)
            updated_dossiers.append(result.dossier)
            for c in claims:
                c.dossiered = True
                store.put("claim", c)

    # -- 4. company candidates (one call per new ticker per dossier) ----------
    new_candidates: list[CompanyCandidate] = []
    for dossier in updated_dossiers:
        dossier_claims = grouped.get(dossier.category, [])
        companies_mentioned = sorted({co for c in dossier_claims for co in c.companies})
        for company_name in companies_mentioned:
            if client is None or not budget_left():
                break
            already_mapped = any(
                c.ticker.lower() == company_name.lower() or c.name.lower() == company_name.lower()
                for c in store.find("company_candidate", CompanyCandidate, dossier_id=dossier.id)
            )
            if already_mapped:
                continue
            result = company_mapping.build_candidate(client, company_name, dossier, dossier_claims, cfg)
            calls_made[0] += 1
            if result.status == "ok" and result.candidate:
                result.candidate.portfolio_overlap = overlap_for(result.candidate.ticker)
                store.put("company_candidate", result.candidate)
                new_candidates.append(result.candidate)

    all_candidates = store.all("company_candidate", CompanyCandidate)
    wally_adapter.write_proposal(all_candidates)

    # -- 5. reports -------------------------------------------------------------
    pdf_path: Path | None = None
    if mode == "weekly":
        all_dossiers = store.all("trend_dossier", TrendDossier)
        ranked = []
        for d in all_dossiers:
            score = None
            if client is not None and budget_left():
                sres = scoring.score_dossier(client, d, cfg)
                calls_made[0] += 1
                if sres.status == "ok":
                    score = sres.score
                    store.put("trend_score", score)
            ranked.append((d, score))
        ranked.sort(
            key=lambda ds: (
                -(ds[1].structural_demand_strength.score if ds[1] else 0),
                -(ds[1].evidence_quality.score if ds[1] else 0),
            )
        )
        inputs = reports.WeeklyReviewInputs(
            week_ending=_today(),
            ranked=ranked,
            conviction_changes=[],
            new_bottlenecks=[d.name for d in updated_dossiers for _ in d.supply_constraints[:1]],
            improving_companies=[c.ticker for c in new_candidates],
            deteriorating_companies=[],
            valuation_concerns=[c.ticker for c in all_candidates if c.valuation.not_covered_reason],
            portfolio_cross_check=[f"{c.ticker}: {', '.join(c.portfolio_overlap)}" for c in new_candidates if c.portfolio_overlap],
            next_to_investigate=[
                f"{c.ticker}: {c.investment_filter.further_work_needed[0]}"
                for c in new_candidates
                if c.investment_filter.further_work_needed
            ],
            strongest_counterarguments=[e for d in updated_dossiers for e in d.evidence_against[:2]],
        )
        subject, text, html_body = reports.build_weekly_review(inputs)
        pdf_html = pdf_render.build_weekly_review_pdf_html(inputs)
        pdf_path = _build_pdf("weekly_review", pdf_html, store, inputs.week_ending)
    else:
        inputs = reports.DailyBriefInputs(
            run_date=_today(),
            new_claims=all_new_claims,
            updated_dossiers=updated_dossiers,
            new_candidates=new_candidates,
            contradicting_evidence=[f"{d.name}: {e}" for d in updated_dossiers for e in d.evidence_against[:2]],
            portfolio_notes=[f"{c.ticker}: {o}" for c in new_candidates for o in c.portfolio_overlap],
            next_indicators=[ind for d in updated_dossiers for ind in d.leading_indicators[:2]],
            emails_processed=len(new_emails),
            emails_skipped_duplicate=ingest.skipped_duplicate,
        )
        subject, text, html_body = reports.build_daily_brief(inputs)
        pdf_html = pdf_render.build_daily_brief_pdf_html(inputs)
        pdf_path = _build_pdf("daily_brief", pdf_html, store, inputs.run_date)

    summary["subject"] = subject
    summary["calls_made"] = calls_made[0]
    summary["updated_dossiers"] = [d.id for d in updated_dossiers]
    summary["new_candidates"] = [c.ticker for c in new_candidates]
    summary["pdf_attached"] = pdf_path is not None

    if send:
        sent = send_email(
            subject, text, html_body,
            attachments=[pdf_path] if pdf_path else None,
            raise_on_error=False, log_prefix="[mickys_macro]",
        )
        summary["email_sent"] = sent

    # -- 6. public dashboard JSON -------------------------------------------
    web.write_dashboard_json(store)

    return summary
