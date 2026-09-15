"""
Fixed reservoir sampler: selects one item uniformly at random from a
data stream of unknown length using exact rational arithmetic and
entropy-efficient interval subdivision.

Maintains two intervals in [0, 1):
  - Decision interval [lo, hi): constrains the hidden random real r
    based on all past keep/replace decisions.
  - Bit interval [r_lo, r_hi): constrains r based on all consumed bits.

For the k-th item, the bottom 1/k fraction of the decision interval
maps to "replace" and the remaining (k-1)/k to "keep".  Bits are
consumed only until the bit interval unambiguously determines which
sub-interval contains r.

Uses fractions.Fraction throughout so probabilities are exact.
"""

from fractions import Fraction


class StreamSampler:
    """Reservoir sampler (k=1) with exact probabilities and near-optimal
    random-bit usage."""

    def __init__(self, bit_source):
        self._bits = bit_source
        self._selected = None
        self._count = 0
        # Decision interval: r must lie in [lo, hi) given past decisions
        self._lo = Fraction(0)
        self._hi = Fraction(1)
        # Bit interval: r must lie in [r_lo, r_hi) given consumed bits
        self._r_lo = Fraction(0)
        self._r_hi = Fraction(1)

    def process(self, item):
        """Incorporate the next stream element."""
        self._count += 1
        if self._count == 1:
            self._selected = item
            return

        k = self._count
        threshold = self._lo + (self._hi - self._lo) / k

        while True:
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
