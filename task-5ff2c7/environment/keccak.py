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
    [62,  6, 43, 14, 61],
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
    0x000000008000000B,
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
            state[x][y] = int.from_bytes(b[offset:offset + 8], 'little')
    return state


def _state_to_bytes(state):
    """Convert 5x5 state array to 200 bytes (little-endian)."""
    b = bytearray(200)
    for x in range(5):
        for y in range(5):
            offset = 8 * (5 * y + x)
            b[offset:offset + 8] = state[x][y].to_bytes(8, 'little')
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
            D[x] = C[(x + 1) % 5] ^ _rot64(C[(x - 1) % 5], 1)

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
