#!/usr/bin/env python3
"""
Fix bugs in keccak.py and sp800_185.py, and implement missing functions.

Bugs identified by comparing intermediate Keccak state against NIST reference:
1. keccak.py theta step: D[x] indices are swapped
2. keccak.py rho offsets: RHO_OFFSETS[2][3] is 14, should be 15
3. keccak.py round constants: RC[11] is 0x000000008000000B, should be 0x000000008000000A
4. sp800_185.py right_encode: length byte is prepended instead of appended
"""

import os

# === Fix keccak.py ===

KECCAK_FIXED = '''\
"""
Keccak-f[1600] permutation implementation.
Provides the core permutation used by SHA-3 and SP 800-185 derived functions.
"""

MASK64 = 0xFFFFFFFFFFFFFFFF


def _rot64(val, n):
    """Rotate a 64-bit value left by n positions."""
    n = n % 64
    return ((val << n) | (val >> (64 - n))) & MASK64


# Rotation offsets for the rho step, indexed as [x][y]
RHO_OFFSETS = [
    [ 0, 36,  3, 41, 18],
    [ 1, 44, 10, 45,  2],
    [62,  6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39,  8, 14],
]

# Round constants for the iota step
RC = [
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
]


def _bytes_to_state(b):
    """Convert 200 bytes to 5x5 state array of 64-bit lanes (little-endian)."""
    state = [[0] * 5 for _ in range(5)]
    for x in range(5):
        for y in range(5):
            offset = 8 * (5 * y + x)
            state[x][y] = int.from_bytes(b[offset:offset + 8], \'little\')
    return state


def _state_to_bytes(state):
    """Convert 5x5 state array to 200 bytes (little-endian)."""
    b = bytearray(200)
    for x in range(5):
        for y in range(5):
            offset = 8 * (5 * y + x)
            b[offset:offset + 8] = state[x][y].to_bytes(8, \'little\')
    return bytes(b)


def keccak_f1600(state_bytes):
    """Apply the Keccak-f[1600] permutation to 200 bytes of state."""
    state = _bytes_to_state(state_bytes)

    for round_idx in range(24):
        # === Theta ===
        C = [0] * 5
        for x in range(5):
            C[x] = state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4]

        D = [0] * 5
        for x in range(5):
            D[x] = C[(x - 1) % 5] ^ _rot64(C[(x + 1) % 5], 1)

        for x in range(5):
            for y in range(5):
                state[x][y] ^= D[x]

        # === Rho ===
        for x in range(5):
            for y in range(5):
                state[x][y] = _rot64(state[x][y], RHO_OFFSETS[x][y])

        # === Pi ===
        B = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                B[y][(2 * x + 3 * y) % 5] = state[x][y]

        # === Chi ===
        for x in range(5):
            for y in range(5):
                state[x][y] = B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y])

        # === Iota ===
        state[0][0] ^= RC[round_idx]

    return _state_to_bytes(state)
'''

# === Fix sp800_185.py ===

SP800_185_FIXED = '''\
"""
SP 800-185: SHA-3 Derived Functions (cSHAKE, KMAC, TupleHash).
Builds on the Keccak-f[1600] permutation from keccak.py.
"""

from keccak import keccak_f1600


def left_encode(x):
    """Encode integer x with its byte-length prepended (SP 800-185 Section 2.3.1)."""
    if x == 0:
        return bytes([1, 0])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, \'big\')
    return bytes([n]) + x_bytes


def right_encode(x):
    """Encode integer x with its byte-length appended (SP 800-185 Section 2.3.1)."""
    if x == 0:
        return bytes([0, 1])
    n = (x.bit_length() + 7) // 8
    x_bytes = x.to_bytes(n, \'big\')
    return x_bytes + bytes([n])


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
    """Generic Keccak sponge construction."""
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

    # Apply padding: suffix byte and final bit
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
'''


def main():
    # Write fixed keccak.py
    with open('/app/keccak.py', 'w') as f:
        f.write(KECCAK_FIXED)
    print("Fixed /app/keccak.py:")
    print("  - Theta step: corrected D[x] index ordering")
    print("  - Rho step: fixed RHO_OFFSETS[2][3] from 14 to 15")
    print("  - Iota step: fixed RC[11] from 0x...0B to 0x...0A")

    # Write fixed sp800_185.py
    with open('/app/sp800_185.py', 'w') as f:
        f.write(SP800_185_FIXED)
    print("Fixed /app/sp800_185.py:")
    print("  - right_encode: moved length byte from prefix to suffix")
    print("  - Implemented KMAC function")
    print("  - Implemented TupleHash function")

    # Validate
    print("\nRunning validation...")
    import importlib
    import sys
    # Force reimport of fixed modules
    for mod in list(sys.modules.keys()):
        if mod in ('keccak', 'sp800_185'):
            del sys.modules[mod]

    sys.path.insert(0, '/app')
    exec(open('/app/validate.py').read())


if __name__ == '__main__':
    main()
