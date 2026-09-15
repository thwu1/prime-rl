"""
Poly1305 one-time authenticator -- standard reference implementation per RFC 8439.

Computes a 16-byte authenticator for a variable-length message using:
  - r: a 16-byte clamped key (128 bits with certain bits forced to 0)
  - s: a 16-byte one-time pad (typically derived from encrypting a nonce)

The authenticator is:
  tag = ( (c_1 * r^q + c_2 * r^(q-1) + ... + c_q * r^1) mod p  +  s ) mod 2^128

where p = 2^130 - 5, and c_i are derived from 16-byte message chunks with
a high-bit sentinel appended (little-endian encoding per RFC 8439).

See: D. J. Bernstein, "The Poly1305-AES message-authentication code"
     RFC 8439, Section 2.5
"""

P = (1 << 130) - 5  # The prime 2^130 - 5


def clamp(r_bytes: bytes) -> bytes:
    """Apply Poly1305 clamping to the r key.

    Certain bits of r are required to be zero:
      r[3], r[7], r[11], r[15] have their top 4 bits cleared
      r[4], r[8], r[12] have their bottom 2 bits cleared
    """
    r = bytearray(r_bytes)
    r[3] &= 0x0F
    r[7] &= 0x0F
    r[11] &= 0x0F
    r[15] &= 0x0F
    r[4] &= 0xFC
    r[8] &= 0xFC
    r[12] &= 0xFC
    return bytes(r)


def le_bytes_to_int(b: bytes) -> int:
    """Convert a byte string to an integer using unsigned little-endian."""
    return int.from_bytes(b, "little")


def int_to_le_bytes(n: int, length: int) -> bytes:
    """Convert a non-negative integer to little-endian bytes of given length."""
    return (n % (1 << (8 * length))).to_bytes(length, "little")


def poly1305(message: bytes, r_bytes: bytes, s_bytes: bytes) -> bytes:
    """Compute a 16-byte Poly1305 authenticator (RFC 8439 standard).

    Args:
        message: The message to authenticate (arbitrary length).
        r_bytes: 16-byte clamped key r (must already satisfy clamping constraints).
        s_bytes: 16-byte one-time pad s.

    Returns:
        16-byte authenticator as bytes.
    """
    r = le_bytes_to_int(r_bytes)
    s = le_bytes_to_int(s_bytes)

    accumulator = 0
    for i in range(0, len(message), 16):
        chunk = message[i : i + 16]
        # Pad the chunk: interpret as little-endian integer, then set
        # bit 8*len(chunk) to 1 (append a 0x01 byte conceptually).
        c = le_bytes_to_int(chunk) + (1 << (8 * len(chunk)))
        accumulator = ((accumulator + c) * r) % P

    tag = (accumulator + s) % (1 << 128)
    return int_to_le_bytes(tag, 16)


def verify(message: bytes, r_bytes: bytes, s_bytes: bytes, tag: bytes) -> bool:
    """Verify a Poly1305 authenticator (constant-time comparison omitted)."""
    expected = poly1305(message, r_bytes, s_bytes)
    return expected == tag
