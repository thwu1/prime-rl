"""
Cryptographic primitives for the vault audit logger.

All log entries are encrypted at rest using AES-256-CTR before being
persisted to the database.  The encryption key is provisioned from the
hardware security module and must never be written to disk in plaintext.
"""

import struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class AuditEncryptor:
    """Encrypts audit log entries with AES-256-CTR.

    Nonce layout (16 bytes total, used as the CTR initial counter block):

        ┌──────────────────┬──────────────────┐
        │  session_id (8B) │   counter  (8B)  │
        └──────────────────┴──────────────────┘

    ``session_id`` is fixed for the lifetime of a daemon process and
    ``counter`` is a monotonically increasing sequence number that starts
    at zero when the daemon boots.
    """

    def __init__(self, key: bytes, session_id: int):
        if len(key) != 32:
            raise ValueError("AES-256 requires a 32-byte key")
        self._key = key
        self._session_id = session_id
        self._counter = 0

    # ── public helpers ────────────────────────────────────────────────

    @property
    def session_id(self) -> int:
        return self._session_id

    @property
    def next_seq(self) -> int:
        """Return the sequence number that will be used by the *next*
        call to :meth:`encrypt`."""
        return self._counter

    # ── core crypto ───────────────────────────────────────────────────

    def _build_nonce(self, seq: int) -> bytes:
        """Pack *session_id* and *seq* into a 16-byte CTR nonce."""
        return struct.pack('<QQ', self._session_id, seq)

    def encrypt(self, plaintext: bytes) -> tuple:
        """Encrypt *plaintext* and return ``(seq_used, ciphertext)``."""
        seq = self._counter
        self._counter += 1
        nonce = self._build_nonce(seq)
        cipher = Cipher(algorithms.AES256(self._key), modes.CTR(nonce))
        enc = cipher.encryptor()
        ct = enc.update(plaintext) + enc.finalize()
        return seq, ct

    # ── factory ───────────────────────────────────────────────────────

    @staticmethod
    def create_session(key: bytes) -> 'AuditEncryptor':
        """Create a new encryptor whose ``session_id`` is the current
        epoch timestamp (seconds)."""
        import time
        return AuditEncryptor(key, int(time.time()))
