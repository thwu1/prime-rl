"""Random value generation for property-based testing."""

import random


class Gen:
    """Random value generator with configurable size.

    The size parameter controls the maximum size of generated collections
    (e.g., list length). Scalar values ignore size.
    """

    def __init__(self, size=100, seed=None):
        self.size = size
        self.rng = random.Random(seed)

    def int(self, signed=True):
        """Generate a random integer.

        10% of the time returns a problem value (MIN, 0, MAX).
        """
        if self.rng.randint(0, 9) == 0:
            if signed:
                return self.rng.choice([-(2**31), 0, 2**31 - 1])
            else:
                return self.rng.choice([0, 1, 2**31 - 1])
        if signed:
            return self.rng.randint(-(2**31), 2**31 - 1)
        else:
            return self.rng.randint(0, 2**31 - 1)

    def small_int(self, lo=0, hi=None):
        """Generate a small integer in [lo, hi]."""
        if hi is None:
            hi = self.size
        return self.rng.randint(lo, hi)

    def bool(self):
        """Generate a random boolean."""
        return self.rng.choice([True, False])

    def char(self):
        """Generate a random character (mostly printable ASCII)."""
        mode = self.rng.randint(0, 99)
        if mode < 70:
            return chr(self.rng.randint(32, 126))
        elif mode < 90:
            return chr(self.rng.randint(0, 127))
        else:
            return chr(self.rng.randint(0, 0xFFFF))

    def list(self, element_gen, max_len=None):
        """Generate a random list.

        element_gen is a no-argument callable that returns a random element.
        """
        if max_len is None:
            max_len = self.size
        n = self.rng.randint(0, max_len)
        return [element_gen() for _ in range(n)]

    def string(self, max_len=None):
        """Generate a random string."""
        if max_len is None:
            max_len = self.size
        n = self.rng.randint(0, max_len)
        return "".join(self.char() for _ in range(n))

    def tuple(self, *element_gens):
        """Generate a random tuple from the given element generators."""
        return tuple(gen() for gen in element_gens)

    def choose(self, items):
        """Choose a random element from items."""
        return self.rng.choice(items)
