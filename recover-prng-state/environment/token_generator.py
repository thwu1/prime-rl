
"""
Token generator using a modified Mersenne Twister PRNG.

This implementation follows the MT19937 structure but uses
NON-STANDARD tempering parameters. The recurrence (twist)
is identical to standard MT19937.
"""

# MT state parameters (standard MT19937)
N = 624
M = 397
MATRIX_A = 0x9908B0DF
UPPER_MASK = 0x80000000  # most significant w-r bits
LOWER_MASK = 0x7FFFFFFF  # least significant r bits

# Custom tempering parameters
_TEMPER_SHIFT_U = 13
_TEMPER_SHIFT_S = 9
_TEMPER_MASK_B = 0xB5A7C4E0
_TEMPER_SHIFT_T = 17
_TEMPER_MASK_C = 0xD3E40000
_TEMPER_SHIFT_L = 15


class ModifiedMT:
    def __init__(self):
        self.mt = [0] * N
        self.index = N + 1

    def seed(self, s):
        self.mt[0] = s & 0xFFFFFFFF
        for i in range(1, N):
            self.mt[i] = (1812433253 * (self.mt[i - 1] ^ (self.mt[i - 1] >> 30)) + i) & 0xFFFFFFFF
        self.index = N

    def _twist(self):
        for i in range(N):
            y = (self.mt[i] & UPPER_MASK) | (self.mt[(i + 1) % N] & LOWER_MASK)
            self.mt[i] = self.mt[(i + M) % N] ^ (y >> 1)
            if y & 1:
                self.mt[i] ^= MATRIX_A
        self.index = 0

    @staticmethod
    def _temper(y):
        y ^= (y >> _TEMPER_SHIFT_U)
        y ^= (y << _TEMPER_SHIFT_S) & _TEMPER_MASK_B
        y ^= (y << _TEMPER_SHIFT_T) & _TEMPER_MASK_C
        y ^= (y >> _TEMPER_SHIFT_L)
        return y & 0xFFFFFFFF

    def extract(self):
        if self.index >= N:
            self._twist()
        y = self.mt[self.index]
        self.index += 1
        return self._temper(y)
