"""
Reservoir sampler: selects one item uniformly at random from a data
stream of unknown length.  Uses a BitSource for random bits.
"""


class StreamSampler:
    """Reservoir sampler (k=1) over an unbounded stream."""

    def __init__(self, bit_source):
        self._bits = bit_source
        self._selected = None
        self._count = 0

    def process(self, item):
        """Incorporate the next stream element."""
        self._count += 1

        if self._count == 1:
            self._selected = item
            return

        k = self._count
        # Generate a random value in [0, 1) to decide keep vs replace
        r = self._generate_uniform()

        # Replace current selection with this item
        if r < 1.0 / (k + 1):
            self._selected = item

    def _generate_uniform(self):
        """Read bits to produce a uniform float in [0, 1)."""
        val = 0
        for _ in range(20):
            val = (val << 1) | self._bits.get_bit()
        return val / (1 << 20)

    def result(self):
        """Return the currently selected item."""
        return self._selected

    def bits_used(self):
        """Return total random bits consumed so far."""
        return self._bits.count
