"""XAES-256-GCM: Extended-nonce AES-256-GCM construction.

This module implements the XAES-256-GCM AEAD algorithm, which provides
authenticated encryption with 256-bit keys and 192-bit nonces. It derives
a standard AES-256-GCM key and nonce from the extended key and nonce using
a CMAC-based KDF.

See /app/spec.md for the full algorithm specification.
"""


from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class XAES256GCM:
    """XAES-256-GCM authenticated encryption.

    Provides encrypt() and decrypt() with 256-bit keys and 192-bit nonces.
    The extended nonce is safe to generate randomly for each message.
    """

    NONCE_SIZE = 24   # 192 bits
    KEY_SIZE = 32     # 256 bits
    TAG_SIZE = 16     # 128 bits

    def __init__(self, key: bytes):
        if len(key) != self.KEY_SIZE:
            raise ValueError(f"Key must be {self.KEY_SIZE} bytes, got {len(key)}")
        self._key = key
        self._k1 = self._derive_k1()

    def _aes_ecb_encrypt_block(self, block: bytes) -> bytes:
        """Encrypt a single 16-byte block with AES-256-ECB using the instance key."""
        cipher = Cipher(algorithms.AES(self._key), modes.ECB())
        encryptor = cipher.encryptor()
        return encryptor.update(block) + encryptor.finalize()

    def _derive_k1(self) -> bytes:
        """Derive CMAC subkey K1 from the encryption key.

        Follows NIST SP 800-38B subkey generation:
        1. L = AES-256_K(0^128)
        2. If MSB(L) == 0: K1 = L << 1
           Else: K1 = (L << 1) XOR R_b
        """
        # Encrypt the zero block to get L
        zero_block = b'\x00' * 16
        L = self._aes_ecb_encrypt_block(zero_block)

        # Check the most significant bit of L
        msb = (L[0] >> 7) & 1

        # Perform the left shift of L by 1 bit across all 16 bytes
        shifted = bytearray(16)
        for i in range(15):
            shifted[i] = ((L[i] << 1) | (L[i + 1] >> 7)) & 0xFF
        shifted[15] = (L[15] << 1) & 0xFF

        # Apply the R_b feedback polynomial for the GF(2^128) doubling
        if msb:
            shifted[0] ^= 0x87

        return bytes(shifted)

    def _derive_subkey_and_nonce(self, nonce: bytes) -> tuple:
        """Derive AES-256-GCM key and nonce from the XAES-256-GCM nonce.

        Constructs M1 and M2 blocks using the counter-mode KDF structure:
          M_i = counter(i) || label || separator || context
        where context is the first 12 bytes of the input nonce.

        Returns:
            (derived_key, derived_nonce): 32-byte key and 12-byte nonce
            for use with standard AES-256-GCM.
        """
        if len(nonce) != self.NONCE_SIZE:
            raise ValueError(f"Nonce must be {self.NONCE_SIZE} bytes, got {len(nonce)}")

        # Build the two KDF input blocks with counter, label 'X', separator, and context
        # Counter is encoded as 2 bytes, label is 0x58 ('X'), separator is 0x00
        m1 = bytes([0x01, 0x00, 0x58, 0x00]) + nonce[:12]
        m2 = bytes([0x02, 0x00, 0x58, 0x00]) + nonce[:12]

        # XOR each block with the CMAC subkey K1
        m1_masked = bytes(a ^ b for a, b in zip(m1, self._k1))
        m2_masked = bytes(a ^ b for a, b in zip(m2, self._k1))

        # Encrypt each masked block to produce 16 bytes of derived key material
        derived_key = (self._aes_ecb_encrypt_block(m1_masked) +
                       self._aes_ecb_encrypt_block(m2_masked))

        # The AES-256-GCM nonce is the last 12 bytes of the input nonce
        derived_nonce = nonce[12:]

        return derived_key, derived_nonce

    def encrypt(self, nonce: bytes, plaintext: bytes, aad: bytes = b'') -> bytes:
        """Encrypt plaintext using XAES-256-GCM.

        Args:
            nonce: 24-byte nonce (safe to generate randomly)
            plaintext: Data to encrypt (may be empty)
            aad: Additional authenticated data (may be empty)

        Returns:
            Ciphertext concatenated with 16-byte authentication tag
        """
        derived_key, derived_nonce = self._derive_subkey_and_nonce(nonce)
        aesgcm = AESGCM(derived_key)
        return aesgcm.encrypt(derived_nonce, plaintext, aad if aad else None)

    def decrypt(self, nonce: bytes, ciphertext: bytes, aad: bytes = b'') -> bytes:
        """Decrypt ciphertext using XAES-256-GCM.

        Args:
            nonce: 24-byte nonce used during encryption
            ciphertext: Ciphertext with appended 16-byte authentication tag
            aad: Additional authenticated data used during encryption

        Returns:
            Decrypted plaintext

        Raises:
            cryptography.exceptions.InvalidTag: If authentication fails
        """
        derived_key, derived_nonce = self._derive_subkey_and_nonce(nonce)
        aesgcm = AESGCM(derived_key)
        return aesgcm.decrypt(derived_nonce, ciphertext, aad if aad else None)
