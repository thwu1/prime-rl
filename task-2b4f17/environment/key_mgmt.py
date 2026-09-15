"""
Secure Key Management Module for IVI-ECU Firmware v4.8.2

Implements the cryptographic infrastructure for protecting diagnostic
data partitions within the firmware storage subsystem.

Architecture:
    RSA key pair -- wraps (encrypts) the AES session key during
    manufacturing.  The RSA public key is embedded in the firmware
    container; the private key is retained by the vehicle
    manufacturer's HSM.

    Before RSA wrapping, the session key is XOR-masked with a value
    derived from the RSA public key's DER encoding.  This binds the
    wrapped key material to the specific RSA key it was intended for,
    providing an additional layer of key-separation even if the RSA
    padding is compromised.

    AES-256-CBC -- encrypts each diagnostic data partition.  A unique
    initialization vector is derived per-partition using HMAC-SHA256
    keyed with the AES session key.

    PKCS #7 padding is applied before encryption so partitions of
    arbitrary length are handled transparently.

Usage (encryption side, manufacturing toolchain):

    mask = FirmwareKeyManager.compute_key_mask(rsa_pubkey_der)
    masked = FirmwareKeyManager.mask_session_key(aes_session_key, rsa_pubkey_der)
    wrapped = rsa_pub.encrypt(masked, PKCS1v15())

    km = FirmwareKeyManager(aes_session_key)
    for idx, part in enumerate(partitions):
        ct = km.encrypt_partition(part, idx)

Usage (decryption side, authorized service tool):

    aes_key = FirmwareKeyManager.unwrap_session_key(wrapped, rsa_priv, rsa_pubkey_der)
    km = FirmwareKeyManager(aes_key)
    for idx in range(num_partitions):
        pt = km.decrypt_partition(ct[idx], idx)
"""

import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class FirmwareKeyManager:
    """Manages cryptographic operations for firmware data protection.

    Key hierarchy
    -------------
    RSA key pair  (asymmetric -- key wrapping with XOR masking)
      +-- AES-256 session key  (symmetric -- data encryption)
            +-- per-partition IVs  (HMAC-derived)

    Key wrapping protocol
    ---------------------
    Before RSA encryption, the session key is XOR-masked with a value
    derived from the RSA public key to bind the wrapped key to its
    intended recipient:

        mask       = SHA-256(rsa_public_key_der)
        masked_key = session_key XOR mask
        wrapped    = RSA_Encrypt(masked_key)

    Unwrapping reverses the process:

        masked_key  = RSA_Decrypt(wrapped)
        session_key = masked_key XOR SHA-256(rsa_public_key_der)
    """

    AES_KEY_SIZE = 32   # 256 bits
    IV_SIZE      = 16   # AES block size

    def __init__(self, aes_session_key: bytes):
        if len(aes_session_key) != self.AES_KEY_SIZE:
            raise ValueError(
                f"AES key must be {self.AES_KEY_SIZE} bytes, "
                f"got {len(aes_session_key)}"
            )
        self._key = aes_session_key

    # ---- Key masking ----

    @staticmethod
    def compute_key_mask(rsa_pubkey_der: bytes) -> bytes:
        """Derive a 32-byte key mask from the RSA public key DER encoding.

        mask = SHA-256(rsa_pubkey_der)
        """
        return hashlib.sha256(rsa_pubkey_der).digest()

    @staticmethod
    def mask_session_key(raw_key: bytes, rsa_pubkey_der: bytes) -> bytes:
        """Apply XOR mask to session key before RSA wrapping.

        masked_key = raw_key XOR SHA-256(rsa_pubkey_der)
        """
        mask = FirmwareKeyManager.compute_key_mask(rsa_pubkey_der)
        return bytes(a ^ b for a, b in zip(raw_key, mask))

    # ---- IV derivation ----

    def _derive_iv(self, partition_index: int) -> bytes:
        """Derive a deterministic, partition-specific IV.

        iv = HMAC-SHA256(session_key, big-endian uint32 of index)[:16]
        """
        idx_bytes = struct.pack(">I", partition_index)
        return hmac.new(self._key, idx_bytes, hashlib.sha256).digest()[
            : self.IV_SIZE
        ]

    # ---- Partition encryption / decryption ----

    def encrypt_partition(self, data: bytes, partition_index: int) -> bytes:
        """Encrypt *data* with AES-256-CBC using a partition-specific IV."""
        iv = self._derive_iv(partition_index)
        pad_len = 16 - (len(data) % 16)
        padded = data + bytes([pad_len]) * pad_len
        enc = Cipher(algorithms.AES(self._key), modes.CBC(iv)).encryptor()
        return enc.update(padded) + enc.finalize()

    def decrypt_partition(self, ciphertext: bytes, partition_index: int) -> bytes:
        """Decrypt a partition and strip PKCS #7 padding."""
        iv = self._derive_iv(partition_index)
        dec = Cipher(algorithms.AES(self._key), modes.CBC(iv)).decryptor()
        padded = dec.update(ciphertext) + dec.finalize()
        return padded[: -padded[-1]]

    # ---- Key wrapping helpers ----

    @staticmethod
    def unwrap_session_key(wrapped_key: bytes, rsa_private_key,
                           rsa_pubkey_der: bytes) -> bytes:
        """Decrypt and unmask the AES session key.

        Steps:
            1. RSA-decrypt with PKCS#1 v1.5 to recover the masked key
            2. XOR with SHA-256(rsa_pubkey_der) to recover the actual key
        """
        masked = rsa_private_key.decrypt(wrapped_key, asym_padding.PKCS1v15())
        mask = FirmwareKeyManager.compute_key_mask(rsa_pubkey_der)
        return bytes(a ^ b for a, b in zip(masked, mask))
