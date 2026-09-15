"""XAES-256-GCM implementation — Team Gamma.

Independent Python implementation of the XAES-256-GCM AEAD construction
based on the C2SP specification.
"""
from Crypto.Cipher import AES


def _aes256_ecb_encrypt(key, block):
    """Encrypt a single 16-byte block with AES-256 in ECB mode."""
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def derive_key(key, nonce):
    """Derive XAES-256-GCM subkey and sub-nonce.

    The 192-bit nonce is decomposed into two 96-bit halves: one for the
    KDF context and one for the underlying AES-256-GCM nonce.

    Args:
        key: 256-bit (32-byte) input key
        nonce: 192-bit (24-byte) input nonce

    Returns:
        Tuple of (Kx, Nx).
    """
    # Step 1: L = AES-256_K(0^128)
    L = _aes256_ecb_encrypt(key, b"\x00" * 16)
    L_int = int.from_bytes(L, "big")

    # Step 2: CMAC subkey K1 (NIST SP 800-38B Section 6.1)
    msb = L_int >> 127
    K1_int = (L_int << 1) & ((1 << 128) - 1)
    if msb == 1:
        K1_int ^= 0x87
    K1 = K1_int.to_bytes(16, "big")

    # Nonce decomposition: context for KDF, residual for GCM
    nonce_ctx = nonce[12:]   # last 12 bytes as KDF context
    nonce_gcm = nonce[:12]   # first 12 bytes as GCM nonce

    # Steps 3-4: KDF message blocks using context half of nonce
    M1 = b"\x00\x01\x58\x00" + nonce_ctx
    M2 = b"\x00\x02\x58\x00" + nonce_ctx

    # Step 5: Derived key
    M1_x = bytes(a ^ b for a, b in zip(M1, K1))
    M2_x = bytes(a ^ b for a, b in zip(M2, K1))
    Kx = _aes256_ecb_encrypt(key, M1_x) + _aes256_ecb_encrypt(key, M2_x)

    # Step 6: GCM nonce
    Nx = nonce_gcm

    return Kx, Nx


def encrypt(key, nonce, plaintext, aad):
    """Encrypt with XAES-256-GCM."""
    Kx, Nx = derive_key(key, nonce)
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    ct, tag = cipher.encrypt_and_digest(plaintext)
    return ct + tag


def decrypt(key, nonce, ciphertext, aad):
    """Decrypt with XAES-256-GCM."""
    Kx, Nx = derive_key(key, nonce)
    ct_body = ciphertext[:-16]
    tag = ciphertext[-16:]
    cipher = AES.new(Kx, AES.MODE_GCM, nonce=Nx)
    cipher.update(aad)
    return cipher.decrypt_and_verify(ct_body, tag)
