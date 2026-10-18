"""Read-only Gmail ingestion for Micky's Macro's four priority research
sources (brief section 3).

Same mechanism Ned's newsletter scanner already uses and for the same
reason: IMAP with an app password needs no Google Cloud project, no OAuth
consent screen and no refresh token, only ``imaplib`` from the stdlib. The
mailbox is opened with ``readonly=True`` so nothing is ever marked read,
moved, labelled or deleted -- this module has no code path that could write
to Gmail at all, by construction, not just by convention.

Independent of ``ned.newsletter_scanner`` (same small amount of IMAP/MIME
boilerplate duplicated rather than importing Ned's module) so a change to
Ned's news pipeline can never become a Micky's Macro regression and vice
versa -- the same "no coupling" choice the repo already makes between SGX
Slinger and ASX Bob.

Email content is untrusted data, not instructions. Nothing here executes
anything found in a message; the extracted text is handed to
``claim_extraction.py`` behind a prompt that says exactly that.
"""

from __future__ import annotations

import datetime as dt
import email
import email.header
import email.utils
import html
import imaplib
import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable

from .config import RunConfig, SourceRegistry
from .schemas import EmailRecord

MAX_MESSAGES_PER_SOURCE_SEARCH = 200  # IMAP search result cap per rule, before the run-wide cap applies


@dataclass
class IngestRun:
    status: str  # ok | not_configured | failed
    emails: list[EmailRecord] = field(default_factory=list)
    skipped_duplicate: int = 0
    skipped_excluded: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# HTML -> text (identical shape to ned/newsletter_scanner.py's extractor;
# duplicated rather than imported -- see module docstring)
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    _SKIP = {"style", "script", "head", "title"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("http"):
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw_html: str) -> tuple[str, list[str]]:
    p = _TextExtractor()
    try:
        p.feed(raw_html)
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw_html), []
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip(), p.links


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in email.header.decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts).strip()


def _sender_address(msg: email.message.Message) -> str:
    _, addr = email.utils.parseaddr(msg.get("From", ""))
    return addr.strip().lower()


def _body(msg: email.message.Message) -> tuple[str, list[str]]:
    plain, rich = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition", "").lower().startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if part.get_content_type() == "text/html" and not rich:
            rich = text
        elif part.get_content_type() == "text/plain" and not plain:
            plain = text
    if rich:
        return html_to_text(rich)
    links = re.findall(r"https?://\S+", plain)
    return plain.strip(), links


def _gmail_link(message_id: str) -> str:
    mid = message_id.strip("<>")
    if not mid:
        return ""
    q = urllib.parse.quote(f"rfc822msgid:{mid}")
    return f"https://mail.google.com/mail/u/0/#search/{q}"


def _search_terms(registry: SourceRegistry) -> list[str]:
    """Distinguishing substrings to search IMAP FROM on, one per rule.

    Gmail's IMAP FROM search matches as a substring of the From header, so
    a prefix rule (``profgmedia`` catching every ``profgmedia+<sub>@...``
    plus-addressed sub-newsletter) just searches on the prefix; the actual
    sender is re-verified against the full registry after fetch.
    """
    terms: set[str] = set()
    for src in registry.priority_sources:
        for rule in src.rules:
            if rule.match == "exact_sender":
                terms.add(rule.value.strip().lower())
            elif rule.match == "sender_local_prefix":
                terms.add(rule.value.strip().lower())
    return sorted(terms)


def fetch_emails(
    registry: SourceRegistry,
    cfg: RunConfig,
    *,
    since: dt.date,
    already_seen: Callable[[str], bool],
    imap_factory: Callable[[str], imaplib.IMAP4_SSL] | None = None,
) -> IngestRun:
    """Fetch every new message from a priority source received on/after
    *since*. ``already_seen(message_id)`` is the caller's dedup check
    (backed by the store) -- this function never decides persistence.
    """
    if not cfg.imap_user or not cfg.imap_password:
        return IngestRun(
            status="not_configured",
            error="MICKYS_MACRO_IMAP_USER / MICKYS_MACRO_IMAP_PASSWORD (or EMAIL_FROM / "
            "EMAIL_APP_PASSWORD) not set",
        )
    factory = imap_factory or (lambda h: imaplib.IMAP4_SSL(h, timeout=30))
    since_str = since.strftime("%d-%b-%Y")

    out = IngestRun(status="ok")
    try:
        conn = factory(cfg.imap_host)
        conn.login(cfg.imap_user, cfg.imap_password.replace(" ", ""))
        # All Mail, same reason Ned reads it: a Gmail filter that skips the
        # inbox (archives straight to a label) must not hide an issue.
        status, _ = conn.select('"[Gmail]/All Mail"', readonly=True)
        if status != "OK":
            conn.select("INBOX", readonly=True)

        seen_msg_ids: set[bytes] = set()
        for term in _search_terms(registry):
            status, data = conn.search(None, "FROM", f'"{term}"', "SINCE", since_str)
            if status != "OK" or not data or not data[0]:
                continue
            for msg_id in data[0].split()[-MAX_MESSAGES_PER_SOURCE_SEARCH:]:
                if msg_id in seen_msg_ids:
                    continue
                seen_msg_ids.add(msg_id)
                if len(out.emails) >= cfg.max_emails_per_run:
                    break
                status, msg_data = conn.fetch(msg_id, "(BODY.PEEK[])")
                if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                sender = _sender_address(msg)
                source_name = registry.identify_sender(sender)
                if not source_name:
                    continue  # the substring matched, but the full address didn't -- not a real hit
                subject = _decode(msg.get("Subject"))
                if registry.is_excluded_subject(subject):
                    out.skipped_excluded += 1
                    continue
                message_id = msg.get("Message-ID", "") or f"{sender}-{msg_id.decode()}"
                if already_seen(message_id):
                    out.skipped_duplicate += 1
                    continue
                try:
                    received = email.utils.parsedate_to_datetime(msg.get("Date"))
                    if received.tzinfo is None:
                        received = received.replace(tzinfo=dt.timezone.utc)
                except Exception:
                    received = dt.datetime.now(dt.timezone.utc)
                text, links = _body(msg)
                out.emails.append(
                    EmailRecord(
                        message_id=message_id,
                        thread_id=msg.get("References", "").split()[-1] if msg.get("References") else message_id,
                        source_name=source_name,
                        sender=sender,
                        subject=subject,
                        received_at=received.isoformat(),
                        gmail_link=_gmail_link(message_id),
                        article_links=links,
                        raw_text=text,
                    )
                )
        try:
            conn.logout()
        except Exception:
            pass
    except Exception as exc:
        # Never log the address or password: Actions logs on this public repo are public.
        return IngestRun(status="failed", emails=out.emails, error=f"{type(exc).__name__}: {exc}")
    return out
