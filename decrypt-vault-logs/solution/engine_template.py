"""
Secure encryption engine — AES-256-GCM with HKDF-derived keys.

Designed as remediation for vulnerable v1/v2 engines.
"""

import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


class SecureEngine:
    """AES-256-GCM engine with HKDF-derived per-context keys.

    Parameters
    ----------
    master_key : bytes
        32-byte master key material.
    context : str
        Context string for key derivation, ensuring domain separation.
    """

    def __init__(self, master_key: bytes, context: str):
        if len(master_key) != 32:
            raise ValueError("Master key must be 32 bytes")
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=context.encode('utf-8'),
        )
        self._key = hkdf.derive(master_key)
        self._aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext. Returns nonce (12B) || ciphertext || tag (16B)."""
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ct

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt blob produced by encrypt()."""
        nonce = ciphertext[:12]
        ct_and_tag = ciphertext[12:]
        return self._aesgcm.decrypt(nonce, ct_and_tag, None)
