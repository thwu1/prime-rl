"""Sobol quasi-random sequence generator using Gray code enumeration.
Direction numbers from Joe & Kuo (2010).
"""

BITS = 30

# Joe-Kuo direction numbers for dimensions 2-6.
# Format: (polynomial_degree, polynomial_coefficients, initial_direction_numbers)
_JK_PARAMS = [
    (1, 0, [1]),                    # dim 2: x+1
    (2, 1, [1, 1]),                 # dim 3: x^2+x+1
    (3, 1, [1, 1, 1]),             # dim 4: x^3+x+1
    (3, 2, [1, 3, 1]),             # dim 5: x^3+x^2+1
    (4, 1, [1, 1, 3, 3]),          # dim 6: x^4+x+1
]


def _rightmost_zero_bit(n):
    """Return 0-indexed position of the rightmost zero bit in n."""
    pos = 0
    while (n >> pos) & 1:
        pos += 1
    return pos


def _build_direction_numbers(s, a, m_init):
    """Build direction numbers from primitive polynomial parameters using recurrence."""
    v = [0] * BITS
    for i in range(min(s, BITS)):
        v[i] = m_init[i] << (BITS - 1 - i)
    for i in range(s, BITS):
        v[i] = v[i - s] ^ (v[i - s] >> s)
        for k in range(1, s):
            if (a >> (s - 1 - k)) & 1:
                v[i] ^= v[i - k]
    return v


class SobolEngine:
    """Sobol quasi-random number generator supporting up to 6 dimensions."""

    def __init__(self, dimension):
        if not 1 <= dimension <= 6:
            raise ValueError(f"dimension must be 1..6, got {dimension}")
        self.dim = dimension
        self._v = []
        # Dimension 1: Van der Corput base-2
        self._v.append([1 << (BITS - 1 - i) for i in range(BITS)])
        for d in range(1, dimension):
            s, a, m = _JK_PARAMS[d - 1]
            self._v.append(_build_direction_numbers(s, a, m))

    def generate(self, n):
        """Generate n quasi-random points in [0,1)^dim using Gray code enumeration."""
        scale = 1.0 / (1 << BITS)
        x = [0] * self.dim
        result = []
        for i in range(n):
            if i == 0:
                result.append([0.0] * self.dim)
            else:
                c = _rightmost_zero_bit(i)
                for d in range(self.dim):
                    x[d] ^= self._v[d][c]
                result.append([x[d] * scale for d in range(self.dim)])
        return result
