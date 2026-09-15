
"""XAES-256-GCM implementation per the C2SP specification.

XAES-256-GCM is an extended-nonce AEAD that derives an AES-256-GCM subkey
from the input key and the first half of the 192-bit nonce using a
CMAC-AES256-based KDF (NIST SP 800-108r1).
"""

from Crypto.Cipher import AES


def _aes256_encrypt_block(key: bytes, block: bytes) -> bytes:
    """Encrypt a single 16-byte block with AES-256 (ECB mode)."""
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def derive_key(key: bytes, nonce: bytes) -> tuple:
    """Derive (Kx, Nx) from (K, N) per XAES-256-GCM specification.

    Args:
        key: 256-bit (32-byte) input key
        nonce: 192-bit (24-byte) input nonce

    Returns:
        Tuple of (Kx, Nx) where Kx is the 256-bit derived key
        and Nx is the 96-bit derived nonce for AES-256-GCM.
    """
    # Step 1: L = AES-256_K(0x00...0x00)
    L = _aes256_encrypt_block(key, b"\x00" * 16)

    # Step 2: CMAC subkey K1 derivation (NIST SP 800-38B Section 6.1)
    L_int = int.from_bytes(L, "big")
    msb = L_int >> 127
    K1_int = (L_int << 1) & ((1 << 128) - 1)
    if msb == 1:
        K1_int ^= 0x87
    K1 = K1_int.to_bytes(16, "big")

    # Steps 3-4: Construct M1 and M2 (KDF input blocks)
    # Format: counter(2 bytes) || label('X'=0x58) || separator(0x00) || context(N[:12])
    M1 = b"\x00\x01\x58\x00" + nonce[:12]
    M2 = b"\x00\x02\x58\x00" + nonce[:12]

    # Step 5: Kx = AES-256_K(M1 XOR K1) || AES-256_K(M2 XOR K1)
    M1_xor = bytes(a ^ b for a, b in zip(M1, K1))
    M2_xor = bytes(a ^ b for a, b in zip(M2, K1))
    Kx = _aes256_encrypt_block(key, M1_xor) + _aes256_encrypt_block(key, M2_xor)

    # Step 6: Nx = N[12:]
    Nx = nonce[12:]

    return Kx, Nx


def encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt with XAES-256-GCM.

    Args:
        key: 256-bit (32-byte) key
        nonce: 192-bit (24-byte) nonce
        plaintext: arbitrary-length plaintext
        aad: additional authenticated data

    Returns:
        Ciphertext with appended 128-bit authentication tag.
    """
    Kx, Nx = derive_key(key, nonce)
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(plaintext)
    return ct + tag


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Decrypt with XAES-256-GCM.

    Args:
        key: 256-bit (32-byte) key
        nonce: 192-bit (24-byte) nonce
        ciphertext: ciphertext with appended 128-bit authentication tag
        aad: additional authenticated data

    Returns:
        Plaintext on successful authentication.

    Raises:
        ValueError: if authentication fails.
    """
    Kx, Nx = derive_key(key, nonce)
    ct_body = ciphertext[:-16]
    tag = ciphertext[-16:]
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    return cipher.decrypt_and_verify(ct_body, tag)
