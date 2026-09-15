"""
Payload formatters for each log-entry type.

Every formatter returns a ``bytes`` object that becomes the AES-CTR
plaintext.  The payload is a pipe-delimited ASCII string suffixed with
an integrity tag so the decrypting reader can verify round-trip
correctness.
"""

import hashlib


class EntryFormatter:
    """Build plaintext payloads for the five entry types."""

    ENTRY_TYPES = ('AUDIT', 'HEARTBEAT', 'ALERT', 'SECRET', 'ACCESS')

    # ── internal helpers ──────────────────────────────────────────────

    @staticmethod
    def _integrity_tag(body: str) -> str:
        """First 16 hex characters of SHA-256 over *body* (UTF-8)."""
        return hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]

    # ── public formatters ─────────────────────────────────────────────

    @staticmethod
    def format_audit(user: str, action: str, resource: str, ts: int) -> bytes:
        body = f"AUDIT|user={user}|action={action}|resource={resource}|ts={ts}"
        tag = EntryFormatter._integrity_tag(body)
        return f"{body}|tag={tag}".encode('utf-8')

    @staticmethod
    def format_heartbeat(session_id: int, entry_seq: int,
                         event_ts: int) -> bytes:
        """Encode a heartbeat probe.

        Parameters
        ----------
        session_id : int
            The daemon's session identifier (epoch seconds at boot).
        entry_seq : int
            Per-session monotonic sequence number for this entry.
        event_ts : int
            Wall-clock epoch seconds when the heartbeat was emitted.
        """
        body = (f"HEARTBEAT|OK|sid={session_id:016x}"
                f"|seq={entry_seq:08x}|ts={event_ts}")
        tag = EntryFormatter._integrity_tag(body)
        return f"{body}|tag={tag}".encode('utf-8')

    @staticmethod
    def format_alert(level: str, message: str, ts: int) -> bytes:
        body = f"ALERT|level={level}|msg={message}|ts={ts}"
        tag = EntryFormatter._integrity_tag(body)
        return f"{body}|tag={tag}".encode('utf-8')

    @staticmethod
    def format_secret(name: str, value: str) -> bytes:
        body = f"SECRET|{name}={value}"
        tag = EntryFormatter._integrity_tag(body)
        return f"{body}|tag={tag}".encode('utf-8')

    @staticmethod
    def format_access(user: str, granted: bool, resource: str,
                      ts: int) -> bytes:
        status = "GRANTED" if granted else "DENIED"
        body = (f"ACCESS|user={user}|status={status}"
                f"|resource={resource}|ts={ts}")
        tag = EntryFormatter._integrity_tag(body)
        return f"{body}|tag={tag}".encode('utf-8')
