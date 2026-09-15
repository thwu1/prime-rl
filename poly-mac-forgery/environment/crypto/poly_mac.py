"""
Polynomial MAC over GF(2^64).

Computes an authentication tag using polynomial evaluation in the
Galois field GF(2^64), similar to the GHASH construction used in
AES-GCM but operating on 64-bit blocks.

Irreducible polynomial: x^64 + x^4 + x^3 + x + 1
"""

REDUCTION_POLY = 0x1B  # x^4 + x^3 + x + 1
FIELD_BITS = 64
FIELD_MASK = (1 << FIELD_BITS) - 1


def gf64_mul(a, b):
    """
    Multiply two elements in GF(2^64).

    Uses the irreducible polynomial x^64 + x^4 + x^3 + x + 1
    for reduction.

    Args:
        a: int - field element (0 to 2^64-1)
        b: int - field element (0 to 2^64-1)

    Returns:
        int - product a*b in GF(2^64)
    """
    result = 0
    for _ in range(FIELD_BITS):
        if b & 1:
            result ^= a
        b >>= 1
        carry = a >> 63
        a = (a << 1) & FIELD_MASK
        if carry:
            a ^= REDUCTION_POLY
    return result


def compute_mac(message_bytes, auth_key_h, mask_s):
    """
    Compute polynomial MAC tag.

    Splits the message into 8-byte blocks, interprets each as a
    GF(2^64) element, and evaluates the polynomial using Horner's
    method:

        tag = ((m_1 * H ^ m_2) * H ^ m_3) * H ... ^ m_n) * H ^ S
            = m_1*H^n + m_2*H^(n-1) + ... + m_n*H + S

    Args:
        message_bytes: bytes - must be a multiple of 8 bytes
        auth_key_h: int - authentication subkey H (GF(2^64) element)
        mask_s: int - masking value S (GF(2^64) element)

    Returns:
        int - MAC tag (GF(2^64) element)
    """
    assert len(message_bytes) % 8 == 0, "Message must be padded to 8-byte blocks"

    blocks = []
    for i in range(0, len(message_bytes), 8):
        blocks.append(int.from_bytes(message_bytes[i:i+8], 'big'))

    acc = 0
    for block in blocks:
        acc = gf64_mul(acc ^ block, auth_key_h)

    return acc ^ mask_s


def derive_mac_keys(nonce, tea_key, tea_encrypt_func):
    """
    Derive polynomial MAC subkeys from a nonce and TEA key.

    H = TEA_Encrypt(nonce, key)         -- polynomial evaluation point
    S = TEA_Encrypt(nonce ^ 0xFF..FF, key) -- one-time mask

    Both H and S depend on the nonce. Reusing a nonce with different
    messages under the same key means H and S are identical for those
    messages.

    Args:
        nonce: bytes (8 bytes)
        tea_key: bytes (16 bytes)
        tea_encrypt_func: callable - TEA encryption function

    Returns:
        (h, s): tuple of ints - authentication subkey and mask
    """
    h_bytes = tea_encrypt_func(nonce, tea_key)

    s_nonce = bytes([b ^ 0xFF for b in nonce])
    s_bytes = tea_encrypt_func(s_nonce, tea_key)

    h = int.from_bytes(h_bytes, 'big')
    s = int.from_bytes(s_bytes, 'big')

    return h, s
