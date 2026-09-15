"""XAES-256-GCM with CMAC-AES256 support.

Complete implementation of the XAES-256-GCM AEAD algorithm and standalone
CMAC-AES256 function per the specification at /app/spec.md.

"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _double_gf128(value: bytes) -> bytes:
    """Double a value in GF(2^128) with R_b = 0x87 feedback polynomial.

    If MSB_1(value) = 0: result = value << 1
    If MSB_1(value) = 1: result = (value << 1) XOR R_b
    """
    msb = (value[0] >> 7) & 1
    shifted = bytearray(16)
    for i in range(15):
        shifted[i] = ((value[i] << 1) | (value[i + 1] >> 7)) & 0xFF
    shifted[15] = (value[15] << 1) & 0xFF
    if msb:
        shifted[15] ^= 0x87
    return bytes(shifted)


def _aes256_ecb_block(key: bytes, block: bytes) -> bytes:
    """Encrypt a single 16-byte block with AES-256-ECB."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(block) + enc.finalize()


def cmac_aes256(key: bytes, message: bytes) -> bytes:
    """Compute CMAC-AES256 authentication tag per NIST SP 800-38B.

    Implements the full CMAC algorithm with K1/K2 subkey generation,
    multi-block CBC-MAC processing, and 10*-padding for incomplete blocks.

    Args:
        key: 32-byte AES-256 key
        message: Message of arbitrary length (may be empty)

    Returns:
        16-byte CMAC authentication tag
    """
    if len(key) != 32:
        raise ValueError("Key must be 32 bytes")

    # Subkey generation: L -> K1 -> K2
    L = _aes256_ecb_block(key, b'\x00' * 16)
    K1 = _double_gf128(L)
    K2 = _double_gf128(K1)

    # Number of blocks (minimum 1 for empty messages)
    n = max(1, (len(message) + 15) // 16)
    complete_last = len(message) > 0 and len(message) % 16 == 0

    # Prepare the last block M_n*
    last_start = (n - 1) * 16
    last_data = message[last_start:]

    if complete_last:
        # Complete block: XOR with K1
        last_block = bytes(a ^ b for a, b in zip(last_data, K1))
    else:
        # Incomplete/empty block: pad with 10...0, XOR with K2
        padded = bytearray(last_data)
        padded.append(0x80)
        padded.extend(b'\x00' * (15 - len(last_data)))
        last_block = bytes(a ^ b for a, b in zip(padded, K2))

    # CBC-MAC processing
    state = b'\x00' * 16
    for i in range(n - 1):
        block = message[i * 16:(i + 1) * 16]
        xored = bytes(a ^ b for a, b in zip(state, block))
        state = _aes256_ecb_block(key, xored)

    # Final block
    xored = bytes(a ^ b for a, b in zip(state, last_block))
    return _aes256_ecb_block(key, xored)


class XAES256GCM:
    """XAES-256-GCM authenticated encryption with 256-bit keys and 192-bit nonces.

    Uses a CMAC-based KDF to derive an AES-256-GCM key and nonce from the
    extended input key and nonce.
    """

    NONCE_SIZE = 24
    KEY_SIZE = 32
    TAG_SIZE = 16

    def __init__(self, key: bytes):
        if len(key) != self.KEY_SIZE:
            raise ValueError(f"Key must be {self.KEY_SIZE} bytes, got {len(key)}")
        self._key = key
        # Precompute K1 for the KDF (same as CMAC subkey generation step)
        L = _aes256_ecb_block(key, b'\x00' * 16)
        self._k1 = _double_gf128(L)

    def _derive_key_and_nonce(self, nonce: bytes):
        """Derive AES-256-GCM key and nonce from the XAES-256-GCM nonce.

        Constructs M1 and M2 blocks using the counter-mode KDF structure
        and encrypts them after XOR with K1 to produce the derived key.
        The derived nonce is the last 12 bytes of the input nonce.
        """
        if len(nonce) != self.NONCE_SIZE:
            raise ValueError(f"Nonce must be {self.NONCE_SIZE} bytes, got {len(nonce)}")

        # KDF input blocks: counter(i) || label('X') || separator(0x00) || context(N[0:12])
        m1 = bytes([0x00, 0x01, 0x58, 0x00]) + nonce[:12]
        m2 = bytes([0x00, 0x02, 0x58, 0x00]) + nonce[:12]

        # XOR with CMAC subkey K1
        m1_x = bytes(a ^ b for a, b in zip(m1, self._k1))
        m2_x = bytes(a ^ b for a, b in zip(m2, self._k1))

        # Derived key = AES-256_K(M1 XOR K1) || AES-256_K(M2 XOR K1)
        derived_key = (_aes256_ecb_block(self._key, m1_x) +
                       _aes256_ecb_block(self._key, m2_x))

        # Derived nonce = N[12:24] (last 12 bytes)
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
        dk, dn = self._derive_key_and_nonce(nonce)
        return AESGCM(dk).encrypt(dn, plaintext, aad if aad else None)

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
        dk, dn = self._derive_key_and_nonce(nonce)
        return AESGCM(dk).decrypt(dn, ciphertext, aad if aad else None)
