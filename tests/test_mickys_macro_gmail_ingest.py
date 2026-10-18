"""Gmail ingestion tests: a fake IMAP connection stands in for Gmail, so no
test ever touches a real mailbox. Covers read-only enforcement, dedup, and
rejecting the exclude-subject-pattern cross-promo mail."""

from __future__ import annotations

import datetime as dt
import email.utils
from email.message import EmailMessage

from mickys_macro import config as mm_config
from mickys_macro import gmail_ingest


def _raw(sender: str, subject: str, message_id: str, body: str = "Research body.") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "johnmyerscough13@gmail.com"
    msg["Subject"] = subject
    msg["Date"] = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return bytes(msg)


class FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL. Records every call so tests
    can assert the mailbox was opened read-only."""

    def __init__(self, host: str):
        self.host = host
        self.selected_readonly: bool | None = None
        self.logged_out = False
        # term -> list of (msg_id bytes, raw bytes)
        self.messages: dict[str, list[tuple[bytes, bytes]]] = {}

    def login(self, user, password):
        assert password  # never empty -- the caller already checked

    def select(self, mailbox, readonly=False):
        self.selected_readonly = readonly
        return "OK", [b""]

    def search(self, charset, *criteria):
        # criteria like (None, "FROM", '"citrini@substack.com"', "SINCE", "01-Jan-2026")
        # -> ("FROM", '"term"', "SINCE", since)
        term = criteria[1].strip('"').lower()
        hits = self.messages.get(term, [])
        return "OK", [b" ".join(m[0] for m in hits)]

    def fetch(self, msg_id, parts):
        assert "BODY.PEEK" in parts  # read-only fetch -- never marks a message read
        for hits in self.messages.values():
            for mid, raw in hits:
                if mid == msg_id:
                    return "OK", [(b"1 (BODY.PEEK[] {%d}" % len(raw), raw)]
        return "NO", []

    def logout(self):
        self.logged_out = True


def _registry():
    return mm_config.load_source_registry()


def test_ingest_opens_mailbox_readonly():
    fake = FakeIMAP("imap.gmail.com")
    # The search term for an exact_sender rule is the full address.
    fake.messages["citrini@substack.com"] = [(b"1", _raw("citrini@substack.com", "Macro Memo", "<m1@substack.com>"))]
    cfg = mm_config.RunConfig.from_env({"MICKYS_MACRO_IMAP_USER": "me@gmail.com", "MICKYS_MACRO_IMAP_PASSWORD": "app-pw"})
    run = gmail_ingest.fetch_emails(
        _registry(), cfg, since=dt.date(2026, 1, 1), already_seen=lambda mid: False,
        imap_factory=lambda host: fake,
    )
    assert run.status == "ok"
    assert fake.selected_readonly is True
    assert fake.logged_out is True
    assert len(run.emails) == 1
    assert run.emails[0].source_name == "Citrini Research"


def test_ingest_dedups_on_message_id():
    fake = FakeIMAP("imap.gmail.com")
    fake.messages["citrini@substack.com"] = [(b"1", _raw("citrini@substack.com", "Macro Memo", "<m1@substack.com>"))]
    cfg = mm_config.RunConfig.from_env({"MICKYS_MACRO_IMAP_USER": "me@gmail.com", "MICKYS_MACRO_IMAP_PASSWORD": "app-pw"})
    run = gmail_ingest.fetch_emails(
        _registry(), cfg, since=dt.date(2026, 1, 1), already_seen=lambda mid: True,  # already processed
        imap_factory=lambda host: fake,
    )
    assert run.status == "ok"
    assert run.emails == []
    assert run.skipped_duplicate == 1


def test_ingest_rejects_cross_promotion_subject():
    fake = FakeIMAP("imap.gmail.com")
    # Matches the "profgmedia" search substring but is the generic Substack
    # notes digest, not Prof G's own content -- excluded by subject.
    fake.messages["profgmedia"] = [
        (b"1", _raw("profgmedia+prof-g@substack.com", "Scott Galloway and others posted new notes", "<m2@substack.com>"))
    ]
    cfg = mm_config.RunConfig.from_env({"MICKYS_MACRO_IMAP_USER": "me@gmail.com", "MICKYS_MACRO_IMAP_PASSWORD": "app-pw"})
    run = gmail_ingest.fetch_emails(
        _registry(), cfg, since=dt.date(2026, 1, 1), already_seen=lambda mid: False,
        imap_factory=lambda host: fake,
    )
    assert run.emails == []
    assert run.skipped_excluded == 1


def test_ingest_ignores_a_sender_that_only_matches_the_search_substring():
    fake = FakeIMAP("imap.gmail.com")
    # Simulates the search returning a message under the search term, but
    # whose real From address isn't the real Citrini Research sender --
    # must not be classified as that source just because the search hit.
    fake.messages["citrini@substack.com"] = [
        (b"1", _raw("notcitrini@example.com", "Something", "<m3@substack.com>"))
    ]
    cfg = mm_config.RunConfig.from_env({"MICKYS_MACRO_IMAP_USER": "me@gmail.com", "MICKYS_MACRO_IMAP_PASSWORD": "app-pw"})
    run = gmail_ingest.fetch_emails(
        _registry(), cfg, since=dt.date(2026, 1, 1), already_seen=lambda mid: False,
        imap_factory=lambda host: fake,
    )
    assert run.emails == []


def test_ingest_not_configured_without_credentials():
    cfg = mm_config.RunConfig.from_env({})
    run = gmail_ingest.fetch_emails(_registry(), cfg, since=dt.date(2026, 1, 1), already_seen=lambda mid: False)
    assert run.status == "not_configured"


def test_ingest_failure_never_logs_credentials(monkeypatch):
    def _boom(host):
        raise ConnectionError("network unreachable")

    cfg = mm_config.RunConfig.from_env({"MICKYS_MACRO_IMAP_USER": "me@gmail.com", "MICKYS_MACRO_IMAP_PASSWORD": "super-secret"})
    run = gmail_ingest.fetch_emails(
        _registry(), cfg, since=dt.date(2026, 1, 1), already_seen=lambda mid: False, imap_factory=_boom,
    )
    assert run.status == "failed"
    assert "super-secret" not in run.error
