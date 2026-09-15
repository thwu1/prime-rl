"""
SP 800-185: SHA-3 Derived Functions (cSHAKE, KMAC, TupleHash).

Uses the Keccak-f[1600] permutation from the compiled C shared library
libkeccak.so via Python ctypes. The library must be built before importing
this module (run 'make' in /app/).
"""

import ctypes
import os

# Load the Keccak shared library
_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libkeccak.so')
_keccak_lib = ctypes.CDLL(_lib_path)
_keccak_lib.keccak_f1600.argtypes = [ctypes.POINTER(ctypes.c_uint8)]
_keccak_lib.keccak_f1600.restype = None


def keccak_f1600(state_bytes):
    """Apply Keccak-f[1600] permutation to 200 bytes of state via C library."""
    buf = (ctypes.c_uint8 * 200)(*state_bytes)
    _keccak_lib.keccak_f1600(buf)
    return bytes(buf)


def left_encode(x):
    """Encode integer x with its byte-length prepended (SP 800-185 Section 2.3.1)."""
    if x == 0:
        return bytes([1, 0])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, 'big')
    return bytes([n]) + x_bytes


def right_encode(x):
    """Encode integer x with its byte-length appended (SP 800-185 Section 2.3.1)."""
    if x == 0:
        return bytes([0, 1])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, 'big')
    return bytes([n]) + x_bytes


def encode_string(s):
    """Encode a byte string with its bit-length prefix (SP 800-185 Section 2.3.2)."""
    return left_encode(len(s) * 8) + s


def bytepad(X, w):
    """Pad byte string X to a multiple of w bytes (SP 800-185 Section 2.3.3)."""
    z = left_encode(w) + X
    pad_len = w - (len(z) % w)
    if pad_len == w:
        pad_len = 0
    return z + bytes(pad_len)


def _sponge(rate, data, suffix, output_len):
    """Generic Keccak sponge construction.

    Args:
        rate: Rate in bytes (168 for 128-bit security, 136 for 256-bit)
        data: Input data bytes (already includes any prefix from cSHAKE)
        suffix: Domain separation suffix byte (0x1F for SHAKE, 0x04 for cSHAKE)
        output_len: Desired output length in bytes
    """
    state = bytearray(200)

    # Absorb: process full rate-sized blocks
    i = 0
    while i + rate <= len(data):
        for j in range(rate):
            state[j] ^= data[i + j]
        state = bytearray(keccak_f1600(bytes(state)))
        i += rate

    # Remaining partial block
    remaining = len(data) - i
    for j in range(remaining):
        state[j] ^= data[i + j]

    # Apply domain-separation suffix and pad10*1
    state[remaining] ^= suffix
    state[rate - 1] ^= 0x80
    state = bytearray(keccak_f1600(bytes(state)))

    # Squeeze
    output = bytearray()
    while len(output) < output_len:
        output.extend(state[:rate])
        if len(output) < output_len:
            state = bytearray(keccak_f1600(bytes(state)))

    return bytes(output[:output_len])


def cshake(security, X, L, N, S):
    """cSHAKE per SP 800-185 Section 6.2.

    Args:
        security: 128 or 256 (bit security level)
        X: input data (bytes)
        L: requested output length in bits
        N: function name string (bytes)
        S: customization string (bytes)

    Returns:
        Output bytes of length L//8
    """
    rate = 168 if security == 128 else 136

    if len(N) == 0 and len(S) == 0:
        # When N and S are both empty, cSHAKE degenerates to SHAKE
        return _sponge(rate, X, 0x1F, L // 8)

    # Prepend bytepad(encode_string(N) || encode_string(S), rate)
    prefix = bytepad(encode_string(N) + encode_string(S), rate)
    return _sponge(rate, prefix + X, 0x04, L // 8)


def kmac(security, K, X, L, S):
    """KMAC per SP 800-185 Section 8.

    Args:
        security: 128 or 256
        K: key (bytes)
        X: input data (bytes)
        L: requested output length in bits
        S: customization string (bytes)

    Returns:
        MAC output bytes of length L//8
    """
    raise NotImplementedError("KMAC is not yet implemented")


def tuplehash(security, tuples, L, S):
    """TupleHash per SP 800-185 Section 9.

    Args:
        security: 128 or 256
        tuples: list of byte strings
        L: requested output length in bits
        S: customization string (bytes)

    Returns:
        Hash output bytes of length L//8
    """
    raise NotImplementedError("TupleHash is not yet implemented")
