"""SP 800-185 Implementation — Vendor Gamma

Implements cSHAKE, KMAC, and TupleHash per NIST SP 800-185,
using the Keccak-f[1600] permutation from the shared FFI module.
"""

import sys
sys.path.insert(0, '/app')
from keccak_ffi import keccak_f1600


def left_encode(x):
    """Encode integer x with length prepended (SP 800-185 Sec 2.3.1)."""
    if x == 0:
        return bytes([1, 0])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, 'big')
    return bytes([n]) + x_bytes


def right_encode(x):
    """Encode integer x with length appended (SP 800-185 Sec 2.3.1)."""
    if x == 0:
        return bytes([0, 1])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, 'big')
    return x_bytes + bytes([n])


def encode_string(s):
    """Encode byte string with bit-length prefix (SP 800-185 Sec 2.3.2)."""
    return left_encode(len(s) * 8) + s


def bytepad(X, w):
    """Pad to a multiple of w bytes (SP 800-185 Sec 2.3.3)."""
    z = left_encode(w) + X
    pad_len = w - (len(z) % w)
    if pad_len == w:
        pad_len = 0
    return z + bytes(pad_len)


def _sponge(rate, data, suffix, output_len):
    """Keccak sponge: absorb data with given suffix, squeeze output_len bytes."""
    state = bytearray(200)
    i = 0
    while i + rate <= len(data):
        for j in range(rate):
            state[j] ^= data[i + j]
        state = bytearray(keccak_f1600(bytes(state)))
        i += rate
    remaining = len(data) - i
    for j in range(remaining):
        state[j] ^= data[i + j]
    state[remaining] ^= suffix
    state[rate - 1] ^= 0x80
    state = bytearray(keccak_f1600(bytes(state)))
    output = bytearray()
    while len(output) < output_len:
        output.extend(state[:rate])
        if len(output) < output_len:
            state = bytearray(keccak_f1600(bytes(state)))
    return bytes(output[:output_len])


def cshake(security, X, L, N, S):
    """cSHAKE per SP 800-185 Section 6.2."""
    rate = 168 if security == 128 else 136
    if len(N) == 0 and len(S) == 0:
        return _sponge(rate, X, 0x1F, L // 8)
    prefix = bytepad(encode_string(N) + encode_string(S), rate)
    return _sponge(rate, prefix + X, 0x04, L // 8)


def kmac(security, K, X, L, S):
    """KMAC per SP 800-185 Section 8."""
    rate = 168 if security == 128 else 136
    new_X = bytepad(encode_string(K), rate) + X + right_encode(L)
    return cshake(security, new_X, L, b"KMAC", S)


def tuplehash(security, tuples, L, S):
    """TupleHash per SP 800-185 Section 9."""
    Z = b""
    for Xi in tuples:
        Z += encode_string(Xi)
    Z += right_encode(L)
    return cshake(security, Z, L, b"TupleHash", S)
