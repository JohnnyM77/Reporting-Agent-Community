from __future__ import annotations

import os

_ANALYSIS_KEYS = ("verdict", "bull_case", "bear_case", "what_must_be_true", "recommendation", "valuation_status")


def _log(msg: str) -> None:
    print(f"[claude_analyst] {msg}", flush=True)


def analyse_company(
    ticker: str,
    company_name: str,
    summary: dict,
    reasons: list[str],
    news: list[str] | None = None,
    harry_flag: dict | None = None,
) -> dict | None:
    """
    Call Claude (claude-opus-4-6) to produce a structured valuation analysis
    for a flagged company.

    Returns a dict with keys: verdict, bull_case, bear_case,
    what_must_be_true, recommendation — or None if the API key is absent or
    the call fails (non-fatal).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        _log("ANTHROPIC_API_KEY not set — skipping AI analysis.")
        return None

    # Transport (client, response text) is shared/llm.py; the prompt and the
    # section parsing below are this agent's own.
    from shared.llm import make_client, send as llm_send

    try:
        client = make_client(api_key)
    except ImportError:
        _log("anthropic package not installed — skipping AI analysis.")
        return None

    wedge_block = ""
    if summary.get("wedge_position") is not None:
        diag = "\n".join(f"  - {d['question']} {d['answer']}" for d in summary.get("wedge_diagnostics") or [])
        wedge_block = f"""
Value wedge (the BUY/SELL corridor; EPS basis: {summary.get('wedge_eps_basis')}):
  EPS in force: {summary.get('wedge_eps_cents')}c ({summary.get('wedge_eps_period')})
  BUY value: ${summary.get('wedge_buy_value')} ({summary.get('wedge_buy_pe')}x)
  SELL value: ${summary.get('wedge_sell_value')} ({summary.get('wedge_sell_pe')}x)
  Actual PE: {summary.get('wedge_actual_pe')}x
  Position: {summary.get('wedge_zone')} ({summary.get('wedge_position'):.0%} of the way from BUY to SELL)
Deterministic wedge diagnostics (computed from the data, treat as facts):
{diag}
"""
        if summary.get("wedge_low_line"):
            wedge_block += f"  Price history: {summary['wedge_low_line']}\n"
        ol = summary.get("wedge_outlook") or {}
        if ol.get("recover") or ol.get("not_recover"):
            wedge_block += ("Researched case for and against an earnings recovery (from the valuation config; "
                            "weigh it, don't repeat it):\n"
                            + "".join(f"  + {x}\n" for x in ol.get("recover") or [])
                            + "".join(f"  - {x}\n" for x in ol.get("not_recover") or []))
        if summary.get("wedge_forecast"):
            wedge_block += (f"Forward view ({summary.get('wedge_forecast_label')}; an ASSUMPTION set in the valuation "
                            "config, not reported earnings; say so if you use it):\n"
                            + "\n".join(f"  - {x}" for x in summary["wedge_forecast"]) + "\n")

    news_block = ""
    if news:
        headlines = "\n".join(f"  - {h}" for h in news[:10])
        news_block = f"\nRecent news headlines:\n{headlines}"

    if harry_flag is not None:
        framing = (
            "Harry Hindsight, the portfolio's chief sceptic, has read the investment thesis for this holding "
            f"as BROKEN (flagged {harry_flag.get('raised', 'recently')}). His verdict: "
            f"{harry_flag.get('verdict', 'n/a')}\n"
            "Your job is a sell analysis, not a valuation-stretch check: with the thesis broken, should the "
            "position be held, trimmed or exited, and what would have to be true to justify holding? Price "
            "being far from its high is not a reason to hold."
        )
        rec_options = "Hold / Trim position / Exit position"
    else:
        framing = (
            "A company has been flagged as potentially over-valued based on quantitative screens.\n"
            "Your job is to write a concise but rigorous investment analysis."
        )
        rec_options = "Watch Only / Hold but stop adding / Trim position"

    prompt = f"""You are Sunday Sally, a disciplined value investor reviewing Australian ASX-listed equities.
{framing}

Company: {company_name} ({ticker})
Current price: ${summary.get('current_price')}
52-week high: ${summary.get('high_52w')}
Distance to 52-week high: {summary.get('distance_to_high_pct')}%
Alert tier: {summary.get('alert_tier')}

Valuation metrics (current):
  Trailing PE: {summary.get('trailing_pe')}
  Forward PE: {summary.get('forward_pe')}
  EV/EBITDA: {summary.get('ev_ebitda')}
  Price/Sales: {summary.get('price_to_sales')}
  FCF Yield: {summary.get('fcf_yield')}
  Dividend Yield: {summary.get('dividend_yield')}

Historical PE context (your anchor for valuation assessment):
  3-year avg PE: {summary.get('pe_3y_avg')}
  5-year avg PE: {summary.get('pe_5y_avg')}
  10-year avg PE: {summary.get('pe_10y_avg')}
  Valuation percentile vs own history: {summary.get('valuation_percentile')} (higher = more expensive; 80th+ = top quintile stretch)

Quantitative trigger reasons: {'; '.join(reasons) if reasons else 'Near 52-week high'}
{wedge_block}{news_block}

Your valuation assessment should anchor to value, not to the share price. A 52-week high is a trigger to look, never a valuation level. When it fires, the question is "has the PE expanded beyond the rational valuation range (the BUY-SELL wedge)?", not "has the price reached a high?". Use the value wedge where given, and the P/E vs the stock's own history (3y/5y/10y). Distinguish price rising because value rose (EPS growth lifts the whole corridor) from price rising faster than value (multiple expansion). The stock may be near its high but still inside the wedge, or expensive at a lower price if it sits above SELL.

Please respond in the following exact format (fill in each section):

VERDICT: [one sentence summary of current valuation attractiveness]

BULL CASE: [2-3 sentences on what would justify the current price / make the stock a hold]

BEAR CASE: [2-3 sentences on the key risks and why the stock may be expensive]

WHAT MUST BE TRUE: [2-3 specific, falsifiable conditions that must hold for the current price to be fair value]

VALUATION STATUS: [explicit statement: BELOW BUY / INSIDE THE WEDGE (say which third) / ABOVE SELL, and whether the latest move came from earnings or from the multiple]

RECOMMENDATION: [one clear action recommendation: {rec_options}, with brief rationale]"""

    try:
        _log(f"Requesting Claude analysis for {ticker}…")
        response = llm_send(
            client,
            model="claude-opus-4-6",
            # Thinking counts against max_tokens: at 1024 it used the lot on
            # TWE (2026-10-18) and left no answer. Stays under the 8192
            # streaming threshold.
            max_tokens=6000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )

        # Text blocks only (thinking blocks are skipped)
        text = response.text

        if not text:
            _log(f"No text in response for {ticker} (stop_reason={response.stop_reason}).")
            return None

        result: dict[str, str] = {}
        for key, label in [
            ("verdict", "VERDICT:"),
            ("bull_case", "BULL CASE:"),
            ("bear_case", "BEAR CASE:"),
            ("what_must_be_true", "WHAT MUST BE TRUE:"),
            ("valuation_status", "VALUATION STATUS:"),
            ("recommendation", "RECOMMENDATION:"),
        ]:
            start = text.find(label)
            if start == -1:
                result[key] = ""
                continue
            start += len(label)
            # Find next section label or end of string
            next_section = len(text)
            for _, other_label in [
                ("verdict", "VERDICT:"),
                ("bull_case", "BULL CASE:"),
                ("bear_case", "BEAR CASE:"),
                ("what_must_be_true", "WHAT MUST BE TRUE:"),
                ("valuation_status", "VALUATION STATUS:"),
                ("recommendation", "RECOMMENDATION:"),
            ]:
                pos = text.find(other_label, start)
                if pos != -1 and pos < next_section:
                    next_section = pos
            result[key] = text[start:next_section].strip()

        _log(f"Claude analysis complete for {ticker}.")
        return result

    except Exception as exc:
        _log(f"Claude API call failed for {ticker}: {exc}")
        return None
