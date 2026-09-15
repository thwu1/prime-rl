"""
Encryption engine v2 — AES-256-CTR.

Deployed to replace v1 after the ECB weakness was identified.  Uses
Counter mode with a deterministic nonce derived from the daemon's
session identifier and a per-entry sequence number.

Nonce layout (16 bytes, used as the CTR initial counter block):

    ┌──────────────────┬──────────────────┐
    │  session_id (8B) │  entry_seq  (8B) │
    └──────────────────┴──────────────────┘

Both fields are packed as unsigned 64-bit little-endian integers.

``session_id`` is set to the Unix epoch timestamp (seconds) at the
moment the daemon process starts.  ``entry_seq`` is a monotonically
increasing counter that resets to zero on each daemon restart.
"""

import struct
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class CTREngine:
    """AES-256-CTR encryption engine.

    The nonce is composed of the daemon's ``session_id`` (fixed for the
    lifetime of the process) concatenated with the entry sequence number.
    """

    VERSION = 2
    CIPHER_SUITE = 'AES-256-CTR'

    def __init__(self, key: bytes, session_id: int):
        if len(key) != 32:
            raise ValueError("AES-256 requires a 32-byte key")
        self._key = key
        self._session_id = session_id
        self._counter = 0

    @property
    def session_id(self) -> int:
        return self._session_id

    @property
    def next_seq(self) -> int:
        """Return the sequence number that will be used by the *next*
        call to :meth:`encrypt`."""
        return self._counter

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

    @staticmethod
    def create_session(key: bytes) -> 'CTREngine':
        """Create a new engine whose ``session_id`` is the current
        epoch timestamp (seconds)."""
        import time
        return CTREngine(key, int(time.time()))
