"""
KnownBits abstract domain for fixed-width unsigned integers.

Each bit position is in one of three states:
  - Known-0: zero_mask has the bit set
  - Known-1: one_mask has the bit set
  - Unknown:  neither mask has the bit set

Invariant: zero_mask & one_mask == 0 for a valid (non-bottom) element.
If zero_mask & one_mask != 0, the element is bottom (empty set).
"""


class KnownBits:

    __slots__ = ("width", "zero_mask", "one_mask")

    def __init__(self, width, zero_mask, one_mask):
        self.width = width
        mask = (1 << width) - 1
        self.zero_mask = zero_mask & mask
        self.one_mask = one_mask & mask

    # ---- Constructors ----

    @staticmethod
    def top(width):
        """All bits unknown — represents the full value set."""
        return KnownBits(width, 0, 0)

    @staticmethod
    def bottom(width):
        """Conflicting — represents the empty set."""
        mask = (1 << width) - 1
        return KnownBits(width, mask, mask)

    @staticmethod
    def from_constant(width, value):
        """Singleton set containing exactly *value*."""
        mask = (1 << width) - 1
        value = value & mask
        return KnownBits(width, (~value) & mask, value)

    # ---- Predicates ----

    def is_conflict(self):
        """True when zero_mask & one_mask != 0 (empty set / bottom)."""
        return (self.zero_mask & self.one_mask) != 0

    def contains(self, value):
        """True when the unsigned *value* is consistent with the known bits."""
        mask = (1 << self.width) - 1
        value = value & mask
        if value & self.zero_mask:
            return False
        if (~value & mask) & self.one_mask:
            return False
        return True

    # ---- Range helpers ----

    def get_min_unsigned(self):
        """Smallest unsigned value (unknown bits → 0)."""
        return self.one_mask

    def get_max_unsigned(self):
        """Largest unsigned value (unknown bits → 1)."""
        return ((1 << self.width) - 1) & ~self.zero_mask

    # ---- Lattice operations ----

    def meet(self, other):
        """Greatest lower bound (intersection of represented sets)."""
        assert self.width == other.width
        return KnownBits(self.width,
                         self.zero_mask | other.zero_mask,
                         self.one_mask | other.one_mask)

    def join(self, other):
        """Least upper bound (union of represented sets)."""
        assert self.width == other.width
        return KnownBits(self.width,
                         self.zero_mask & other.zero_mask,
                         self.one_mask & other.one_mask)

    # ---- Utilities ----

    def num_known_bits(self):
        """Count of bit positions that are determined (known-0 or known-1)."""
        return bin(self.zero_mask | self.one_mask).count("1")

    def iterate_concrete_values(self):
        """Yield every unsigned value consistent with these known bits."""
        if self.is_conflict():
            return
        unknown = []
        for i in range(self.width):
            if not ((self.zero_mask >> i) & 1) and not ((self.one_mask >> i) & 1):
                unknown.append(i)
        base = self.one_mask
        for combo in range(1 << len(unknown)):
            v = base
            for j, pos in enumerate(unknown):
                if (combo >> j) & 1:
                    v |= 1 << pos
            yield v

    def __eq__(self, other):
        if not isinstance(other, KnownBits):
            return NotImplemented
        return (self.width == other.width
                and self.zero_mask == other.zero_mask
                and self.one_mask == other.one_mask)

    def __hash__(self):
        return hash((self.width, self.zero_mask, self.one_mask))

    def __repr__(self):
        bits = []
        for i in range(self.width - 1, -1, -1):
            if self.one_mask & (1 << i):
                bits.append("1")
            elif self.zero_mask & (1 << i):
                bits.append("0")
            else:
                bits.append("?")
        return f"KB({''.join(bits)})"
