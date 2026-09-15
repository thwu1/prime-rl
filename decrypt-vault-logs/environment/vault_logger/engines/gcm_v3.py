"""
Encryption engine v3 — AES-256-GCM.

Current production engine.  Uses Galois/Counter Mode with a
cryptographically random 12-byte nonce for every encryption operation,
providing both confidentiality and authenticity.

Ciphertext layout returned by :meth:`encrypt`:

    ┌────────────┬──────────────────────────┬──────────────────┐
    │ nonce (12B)│       ciphertext         │  GCM tag (16B)   │
    └────────────┴──────────────────────────┴──────────────────┘

The nonce is prepended and the 16-byte authentication tag is appended
automatically by the AESGCM primitive.
"""

import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class GCMEngine:
    """AES-256-GCM authenticated encryption engine.

    Each encryption generates a fresh 12-byte random nonce, ensuring
    nonce uniqueness with overwhelming probability.
    """

    VERSION = 3
    CIPHER_SUITE = 'AES-256-GCM'

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-256 requires a 32-byte key")
        self._aesgcm = AESGCM(key)

    def encrypt(self, plaintext: bytes, aad: bytes = None) -> bytes:
        """Encrypt with a fresh random nonce.

        Returns ``nonce ‖ ciphertext ‖ tag`` as a single blob.
        """
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext, aad)
        return nonce + ct  # AESGCM appends the 16-byte tag automatically

    def decrypt(self, blob: bytes, aad: bytes = None) -> bytes:
        """Decrypt a blob produced by :meth:`encrypt`."""
        nonce = blob[:12]
        ct_and_tag = blob[12:]
        return self._aesgcm.decrypt(nonce, ct_and_tag, aad)
