"""The annual thesis refresh — once a year, on each company's own cycle.

A thesis written at entry and never revisited rots quietly: the business moves,
the numbers move, and the file still argues the case from two years ago. So
once a year, after the company reports its full-year result, Theo asks you to
come back in and update the thesis against the new numbers. It is a prompt, not
a gate — declining is fine, but the schedule is on the record either way.

The cycle is per company, because reporting dates are. Most ASX names balance on
30 June and report in August; a calendar-year reporter balances on 31 December
and reports in February. ``reporting_calendar`` in the thesis frontmatter sets
the month; where it is missing, June is assumed and the assumption is stated
rather than hidden.

This module only reads theses. The actual "the annual report just landed" nudge
comes from Theo reading Bob's dashboard JSON (see ``signals.from_bob_annual``);
this is the durable schedule that keeps the prompt visible until the refresh is
actually written, and that works even in the months Bob's digest has rolled on.
"""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from .thesis import Thesis

# ASX listed entities file the full-year accounts (Appendix 4E) within two
# months of the balance date. Two months after year-end is the earliest the
# result is reliably out, so that is when the refresh becomes "available".
REPORTING_LAG_MONTHS = 2

_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# A review with one of these triggers, or any dated review at all, counts as the
# year's refresh. The schedule is lenient on purpose: if you reviewed the thesis
# for any reason after the result landed, the annual question is answered.
ANNUAL_TRIGGERS = ("ANNUAL", "ANNUAL_REPORT", "ANNUAL_REFRESH")


def _shift_month(year: int, month: int, by: int) -> tuple[int, int]:
    index = (month - 1) + by
    return year + index // 12, index % 12 + 1


def expected_report_date(fy_end_month: int, today: dt.date) -> dt.date:
    """The most recent date, on or before ``today``, by which a full-year result
    for this cycle should have landed.

    For a June balance date (``fy_end_month = 6``) the result is expected from
    1 August; for December, from 1 February of the following year.
    """
    report_year, report_month = _shift_month(today.year, fy_end_month, REPORTING_LAG_MONTHS)
    candidate = dt.date(report_year, report_month, 1)
    if candidate <= today:
        return candidate
    # This year's result is not due yet — the live cycle is the previous one.
    report_year, report_month = _shift_month(today.year - 1, fy_end_month, REPORTING_LAG_MONTHS)
    return dt.date(report_year, report_month, 1)


def last_annual_review(thesis: Thesis, since: dt.date) -> dt.date | None:
    """The date of the most recent review on or after ``since`` — the refresh
    that answers the current cycle, whatever triggered it."""
    dates = [r.date for r in thesis.reviews if r.date and r.date >= since]
    return max(dates) if dates else None


def basis_label(thesis: Thesis) -> str:
    month = _MONTH_ABBR.get(thesis.fy_end_month, "?")
    kind = "Calendar" if thesis.fy_end_month == 12 else "FY"
    label = f"{kind} ({month})"
    return f"{label}, assumed" if thesis.reporting_calendar_assumed else label


def annual_status(thesis: Thesis, today: dt.date | None = None) -> dict:
    """One company's annual-refresh state, public-safe (no amounts, ever)."""
    today = today or dt.date.today()
    fy_end = thesis.fy_end_month
    expected = expected_report_date(fy_end, today)
    reviewed = last_annual_review(thesis, expected)
    due = (not thesis.is_exited) and reviewed is None and today >= expected
    last_any = thesis.last_review.date if thesis.last_review else None
    return {
        "ticker": thesis.ticker,
        "name": thesis.name or thesis.ticker,
        "basis": basis_label(thesis),
        "fy_end_month": fy_end,
        "assumed": thesis.reporting_calendar_assumed,
        "cycle_report_date": expected.isoformat(),
        "last_review": last_any.isoformat() if last_any else None,
        "reviewed_this_cycle": reviewed is not None,
        "due": due,
        "exited": thesis.is_exited,
    }


def due_now(theses: Sequence[Thesis], today: dt.date | None = None) -> list[dict]:
    """Every live thesis whose annual refresh is now outstanding, due first."""
    today = today or dt.date.today()
    rows = [annual_status(t, today) for t in theses if not t.is_exited]
    rows.sort(key=lambda r: (not r["due"], r["cycle_report_date"]))
    return rows
