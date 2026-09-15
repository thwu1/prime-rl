
import pytest
import sys

sys.path.insert(0, "/app")

from bitsource import BitSource
from sampler import StreamSampler


# ---------------------------------------------------------------------------
# Lightweight bit source for deterministic hand-traced tests
# ---------------------------------------------------------------------------

class ListBitSource:
    """Provides bits from a predetermined list (no C library needed)."""

    def __init__(self, bits):
        self._bits = list(bits)
        self._pos = 0

    def get_bit(self):
        b = self._bits[self._pos]
        self._pos += 1
        return b

    @property
    def count(self):
        return self._pos


# ---------------------------------------------------------------------------
# C library integration
# ---------------------------------------------------------------------------

class TestLibraryIntegration:
    def test_bitsource_creates(self):
        bs = BitSource(seed=42)
        assert bs.count == 0

    def test_bitsource_returns_bits(self):
        bs = BitSource(seed=42)
        bit = bs.get_bit()
        assert bit in (0, 1)
        assert bs.count == 1

    def test_bitsource_deterministic(self):
        """Same seed must produce the same bit sequence."""
        bs1 = BitSource(seed=99)
        bits1 = [bs1.get_bit() for _ in range(100)]
        bs2 = BitSource(seed=99)
        bits2 = [bs2.get_bit() for _ in range(100)]
        assert bits1 == bits2

    def test_bitsource_different_seeds(self):
        """Different seeds produce different sequences."""
        bs1 = BitSource(seed=1)
        bits1 = [bs1.get_bit() for _ in range(50)]
        bs2 = BitSource(seed=2)
        bits2 = [bs2.get_bit() for _ in range(50)]
        assert bits1 != bits2


# ---------------------------------------------------------------------------
# Basic correctness (algorithm-independent properties)
# ---------------------------------------------------------------------------

class TestBasicCorrectness:

    def test_single_item_selected(self):
        """One item must always be selected."""
        s = StreamSampler(ListBitSource([0] * 10))
        s.process("only")
        assert s.result() == "only"

    def test_single_item_zero_bits(self):
        """Selecting from one item should consume no random bits."""
        s = StreamSampler(ListBitSource([0] * 10))
        s.process("x")
        assert s.bits_used() == 0

    def test_two_items_one_bit(self):
        """Selecting from two items should consume exactly 1 bit."""
        for bits in [[0] + [0] * 20, [1] + [0] * 20]:
            s = StreamSampler(ListBitSource(bits))
            s.process("a")
            s.process("b")
            assert s.bits_used() == 1, (
                f"Expected 1 bit for n=2, got {s.bits_used()}"
            )
            assert s.result() in ("a", "b")

    def test_two_items_complementary(self):
        """Opposite first bits must select different items for n=2."""
        s0 = StreamSampler(ListBitSource([0] + [0] * 20))
        s0.process("a")
        s0.process("b")
        s1 = StreamSampler(ListBitSource([1] + [0] * 20))
        s1.process("a")
        s1.process("b")
        assert {s0.result(), s1.result()} == {"a", "b"}

    def test_deterministic_same_bits(self):
        """Same bit sequence must always produce the same selection."""
        results = []
        for _ in range(5):
            s = StreamSampler(ListBitSource([1, 0, 1, 0, 1] + [0] * 50))
            for i in range(5):
                s.process(i)
            results.append(s.result())
        assert all(r == results[0] for r in results)


# ---------------------------------------------------------------------------
# Statistical fairness (using C-backed PRNG)
# ---------------------------------------------------------------------------

class TestStatisticalFairness:

    @staticmethod
    def _check_fairness(n, num_trials, seed_start, tolerance=0.20):
        counts = [0] * n
        for trial in range(num_trials):
            s = StreamSampler(BitSource(seed=seed_start + trial))
            for i in range(n):
                s.process(i)
            counts[s.result()] += 1

        expected = num_trials / n
        for i in range(n):
            lo = expected * (1 - tolerance)
            hi = expected * (1 + tolerance)
            assert lo < counts[i] < hi, (
                f"n={n}, item {i}: count={counts[i]}, "
                f"expected~{expected:.0f}, bounds=[{lo:.0f}, {hi:.0f}]"
            )

    def test_fairness_n5(self):
        self._check_fairness(n=5, num_trials=50000, seed_start=10000)

    def test_fairness_n10(self):
        self._check_fairness(n=10, num_trials=50000, seed_start=100000)

    def test_fairness_n20(self):
        self._check_fairness(n=20, num_trials=40000, seed_start=200000)


# ---------------------------------------------------------------------------
# Bit-consumption efficiency
# ---------------------------------------------------------------------------

class TestEfficiency:

    def test_bits_for_two_always_one(self):
        """Two items always needs exactly 1 bit, for many seeds."""
        for seed in [1, 42, 100, 999, 12345]:
            s = StreamSampler(BitSource(seed=seed))
            s.process(0)
            s.process(1)
            assert s.bits_used() == 1, (
                f"seed={seed}: expected 1 bit, got {s.bits_used()}"
            )

    def test_average_bits_sublinear(self):
        """Average total bits consumed should be well under n."""
        n = 100
        total_bits = 0
        trials = 2000
        for trial in range(trials):
            s = StreamSampler(BitSource(seed=500000 + trial))
            for i in range(n):
                s.process(i)
            total_bits += s.bits_used()

        avg_bits = total_bits / trials
        assert avg_bits < n, (
            f"Average bits {avg_bits:.1f} should be sublinear (< {n})"
        )

    def test_bits_monotonic(self):
        """bits_used() should never decrease as items are processed."""
        s = StreamSampler(BitSource(seed=777))
        prev = 0
        for i in range(50):
            s.process(i)
            cur = s.bits_used()
            assert cur >= prev, (
                f"bits_used decreased from {prev} to {cur} at item {i}"
            )
            prev = cur


# ---------------------------------------------------------------------------
# Large-stream performance
# ---------------------------------------------------------------------------

class TestLargeStream:

    def test_n2000(self):
        """Must handle 2000 items without timeout or memory blowup."""
        s = StreamSampler(BitSource(seed=42424242))
        for i in range(2000):
            s.process(i)
        assert 0 <= s.result() < 2000
        bits_used = s.bits_used()
        assert 0 < bits_used < 20000


# ---------------------------------------------------------------------------
# Interface and misc
# ---------------------------------------------------------------------------

class TestInterface:

    def test_arbitrary_item_types(self):
        """Items can be any Python object."""
        s = StreamSampler(ListBitSource([0] + [0] * 30))
        s.process("hello")
        s.process("world")
        assert s.result() == "world" or s.result() == "hello"
        assert s.bits_used() == 1

    def test_result_stable_between_processes(self):
        """result() should be callable between successive process() calls."""
        s = StreamSampler(ListBitSource([1, 1, 1] + [0] * 30))
        s.process("a")
        assert s.result() == "a"
        s.process("b")
        r = s.result()
        assert r in ("a", "b")
