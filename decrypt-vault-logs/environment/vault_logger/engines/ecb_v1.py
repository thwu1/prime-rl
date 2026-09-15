"""
Encryption engine v1 — AES-128-ECB.

Initial deployment engine.  Uses Electronic Codebook mode with PKCS#7
padding.  Each 16-byte plaintext block is encrypted independently with
the same key.

Key source
----------
The v1 AES-128 key was exported from the HSM as an RSA-OAEP wrapped
blob stored at ``/app/keys/v1_wrapped.bin``.  To recover the raw key,
unwrap it with the vault RSA private key at ``/app/keys/vault_priv.pem``
(passphrase recorded in ``/app/vault_logger/config.py``).
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


class ECBEngine:
    """AES-128-ECB encryption engine.

    Encrypts each entry as a standalone PKCS#7-padded, AES-128-ECB
    ciphertext.  No initialisation vector is used — identical plaintext
    always produces identical ciphertext.
    """

    VERSION = 1
    CIPHER_SUITE = 'AES-128-ECB'

    def __init__(self, key: bytes):
        if len(key) != 16:
            raise ValueError("AES-128 requires a 16-byte key")
        self._key = key

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt *plaintext* with PKCS#7 padding and AES-128-ECB."""
        padder = PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES128(self._key), modes.ECB())
        enc = cipher.encryptor()
        return enc.update(padded) + enc.finalize()

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt *ciphertext* and strip PKCS#7 padding."""
        cipher = Cipher(algorithms.AES128(self._key), modes.ECB())
        dec = cipher.decryptor()
        padded = dec.update(ciphertext) + dec.finalize()
        unpadder = PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
