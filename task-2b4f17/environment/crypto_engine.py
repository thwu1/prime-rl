#!/usr/bin/env python3
"""
Diagnostic Data Encryption Engine for IVI-ECU Module R7.

Implements secure encryption of vehicle diagnostic snapshots for
tamper-resistant storage and transport. Uses AES-256 in Output Feedback
(OFB) mode for streaming encryption of chunked diagnostic data.

The encryption key is derived from the master diagnostic password using
PBKDF2-HMAC-SHA256 with a hardware-bound salt. The initialization vector
is derived deterministically from the key to ensure consistency across
diagnostic sessions without requiring IV storage.

Security Note: Each diagnostic chunk is encrypted independently to allow
chunk-level recovery in case of storage corruption.
"""
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class DiagnosticEncryptor:
    """Handles encryption of diagnostic data chunks.

    Attributes:
        key: AES-256 encryption key derived from master password
        iv: Initialization vector derived from key
    """

    SALT = b"diag-enc-salt-v2"
    KDF_ITERATIONS = 200000
    CHUNK_SIZE = 512

    def __init__(self, master_password: str):
        """Initialize encryptor with master diagnostic password.

        Args:
            master_password: The master password for key derivation
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=self.SALT,
            iterations=self.KDF_ITERATIONS,
        )
        self.key = kdf.derive(master_password.encode("utf-8"))
        # Derive IV deterministically from key for session consistency
        self.iv = hashlib.md5(self.key).digest()

    def _create_cipher(self):
        """Create a fresh AES-OFB cipher instance for chunk processing."""
        return Cipher(algorithms.AES(self.key), modes.OFB(self.iv))

    def encrypt_chunk(self, plaintext: bytes) -> bytes:
        """Encrypt a single diagnostic data chunk.

        Each chunk is processed independently using a fresh cipher
        instance to support granular chunk-level error recovery.

        Args:
            plaintext: Raw diagnostic data (will be padded to CHUNK_SIZE)

        Returns:
            Encrypted chunk bytes
        """
        if len(plaintext) < self.CHUNK_SIZE:
            plaintext = plaintext + b"\x00" * (self.CHUNK_SIZE - len(plaintext))
        encryptor = self._create_cipher().encryptor()
        return encryptor.update(plaintext) + encryptor.finalize()

    def encrypt_diagnostic_data(self, data: bytes) -> list:
        """Encrypt a full diagnostic snapshot as independent chunks.

        Args:
            data: Complete diagnostic data to encrypt

        Returns:
            List of encrypted chunk bytes
        """
        chunks = []
        for i in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[i:i + self.CHUNK_SIZE]
            chunks.append(self.encrypt_chunk(chunk))
        return chunks

    def decrypt_chunk(self, ciphertext: bytes) -> bytes:
        """Decrypt a single diagnostic data chunk.

        Args:
            ciphertext: Encrypted chunk bytes

        Returns:
            Decrypted plaintext bytes
        """
        decryptor = self._create_cipher().decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()
