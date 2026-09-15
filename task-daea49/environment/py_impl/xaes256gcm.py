"""XAES-256-GCM: Extended-nonce AES-256-GCM with CMAC-AES256 support.

Fix the cmac_aes256() function and implement the XAES256GCM class
following the specification at /app/spec.md.

Constraint: Only use raw AES-ECB block cipher operations from the
cryptography library for CMAC. Do NOT import or use any CMAC library/API.
You may use AESGCM for the final AES-GCM encryption step.

See /app/spec.md for the full algorithm specification.
"""


from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _double_gf128(value: bytes) -> bytes:
    """Double a value in GF(2^128) with the reduction polynomial."""
    msb = (value[0] >> 7) & 1
    shifted = bytearray(16)
    for i in range(15):
        shifted[i] = ((value[i] << 1) | (value[i + 1] >> 7)) & 0xFF
    shifted[15] = (value[15] << 1) & 0xFF
    if msb:
        shifted[15] ^= 0xE1
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

    # Prepare the final block M_n*
    last_start = (n - 1) * 16
    last_data = message[last_start:]

    if complete_last:
        # Complete block: XOR with subkey
        last_block = bytes(a ^ b for a, b in zip(last_data, K2))
    else:
        # Incomplete/empty block: pad with 10...0, XOR with subkey
        padded = bytearray(last_data)
        padded.append(0x80)
        padded.extend(b'\x00' * (15 - len(last_data)))
        last_block = bytes(a ^ b for a, b in zip(padded, K1))

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
    """XAES-256-GCM authenticated encryption.

    Required interface:
    - __init__(self, key: bytes): 32-byte key, raises ValueError if wrong size
    - encrypt(self, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes
      Nonces are 24 bytes. Returns ciphertext || 16-byte tag.
    - decrypt(self, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes
      Returns plaintext. Raises cryptography.exceptions.InvalidTag on failure.
    """

    NONCE_SIZE = 24
    KEY_SIZE = 32
    TAG_SIZE = 16

    def __init__(self, key: bytes):
        raise NotImplementedError("Implement per /app/spec.md")

    def encrypt(self, nonce: bytes, plaintext: bytes, aad: bytes = b'') -> bytes:
        raise NotImplementedError("Implement per /app/spec.md")

    def decrypt(self, nonce: bytes, ciphertext: bytes, aad: bytes = b'') -> bytes:
        raise NotImplementedError("Implement per /app/spec.md")
