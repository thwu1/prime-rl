"""
Entropy-efficient reservoir sampler using interval subdivision.

Uses a single lazy source of random bits to simulate a uniform random real
r in [0, 1).  Maintains two intervals:

  - Decision interval [lo, hi):  narrows with each keep/replace decision.
  - Bit interval [r_lo, r_hi):   narrows each time a bit is consumed.

The intersection of these two intervals constrains where r can lie.
Bits are consumed only until the intersection is entirely on one side
of the decision threshold, making the keep/replace choice unambiguous.

All arithmetic uses fractions.Fraction so that probabilities are exact.
"""

from fractions import Fraction


class IntervalReservoir:
    """Reservoir sampler (k=1) with near-optimal random-bit usage."""

    def __init__(self, bit_source):
        self._bits = bit_source
        self._selected = None
        self._count = 0
        # Decision interval: r is known to be in [lo, hi) from past decisions
        self._lo = Fraction(0)
        self._hi = Fraction(1)
        # Bit interval: r is known to be in [r_lo, r_hi) from consumed bits
        self._r_lo = Fraction(0)
        self._r_hi = Fraction(1)

    def process(self, item):
        """Incorporate the next stream element."""
        self._count += 1
        if self._count == 1:
            # First element is always selected; no randomness needed.
            self._selected = item
            return

        k = self._count
        threshold = self._lo + (self._hi - self._lo) / k

        # Determine whether r < threshold (replace) or r >= threshold (keep)
        # by consuming bits lazily until the answer is unambiguous.
        while True:
            # Effective bounds on r from both intervals
            eff_lo = max(self._r_lo, self._lo)
            eff_hi = min(self._r_hi, self._hi)

            if eff_hi <= threshold:
                # r < threshold for certain -> replace
                self._selected = item
                self._hi = threshold
                return

            if eff_lo >= threshold:
                # r >= threshold for certain -> keep
                self._lo = threshold
                return

            # Ambiguous: halve the bit interval by consuming one bit
            mid = (self._r_lo + self._r_hi) / 2
            if self._bits.get_bit() == 0:
                self._r_hi = mid
            else:
                self._r_lo = mid

    def result(self):
        """Return the currently selected item."""
        return self._selected

    def bits_used(self):
        """Return total random bits consumed so far."""
        return self._bits.count
