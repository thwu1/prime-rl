
import sys
import time
import pytest

sys.path.insert(0, "/app")

from naive_bpe import NaiveBPETrainer
from fast_bpe import FastBPETrainer


# ---------------------------------------------------------------------------
# Merge-sequence identity tests
# ---------------------------------------------------------------------------

class TestMergeIdentity:
    """FastBPETrainer must produce identical merge sequences to NaiveBPETrainer."""

    def test_small_repeated_text(self):
        text = "aaabdaaabac" * 100
        num_merges = 20

        naive = NaiveBPETrainer()
        fast = FastBPETrainer()

        nm = naive.train(text, num_merges)
        fm = fast.train(text, num_merges)

        assert len(nm) == len(fm), (
            f"Merge count differs: naive={len(nm)}, fast={len(fm)}"
        )
        for i, (n, f) in enumerate(zip(nm, fm)):
            assert n == f, f"Merge {i} differs: naive={n}, fast={f}"

    def test_medium_corpus(self):
        with open("/app/data/corpus.txt") as fh:
            text = fh.read()[:50000]
        num_merges = 200

        naive = NaiveBPETrainer()
        fast = FastBPETrainer()

        nm = naive.train(text, num_merges)
        fm = fast.train(text, num_merges)

        assert len(nm) == len(fm), (
            f"Merge count differs: naive={len(nm)}, fast={len(fm)}"
        )
        for i, (n, f) in enumerate(zip(nm, fm)):
            assert n == f, f"Merge {i} differs: naive={n}, fast={f}"

    def test_varied_content(self):
        text = "hello world! 123 testing... the quick brown fox " * 50
        text += "aaabbbccc " * 100
        text += "x y z " * 200
        num_merges = 50

        naive = NaiveBPETrainer()
        fast = FastBPETrainer()

        nm = naive.train(text, num_merges)
        fm = fast.train(text, num_merges)

        for i, (n, f) in enumerate(zip(nm, fm)):
            assert n == f, f"Merge {i} differs: naive={n}, fast={f}"


# ---------------------------------------------------------------------------
# Encode / decode tests
# ---------------------------------------------------------------------------

class TestEncodeDecode:
    """Encode and decode must be correct and consistent with naive."""

    def test_roundtrip_basic(self):
        text = "hello world this is a test of the tokenizer"
        fast = FastBPETrainer()
        fast.train(text, 50)

        for t in ["hello world", "this is a test", "tokenizer"]:
            assert fast.decode(fast.encode(t)) == t, f"Round-trip failed: {t!r}"

    def test_roundtrip_corpus(self):
        with open("/app/data/corpus.txt") as fh:
            text = fh.read()[:10000]

        fast = FastBPETrainer()
        fast.train(text, 200)

        chunk = text[:2000]
        assert fast.decode(fast.encode(chunk)) == chunk

    def test_encode_matches_naive(self):
        text = "the quick brown fox jumps over the lazy dog " * 20
        num_merges = 30

        naive = NaiveBPETrainer()
        fast = FastBPETrainer()
        naive.train(text, num_merges)
        fast.train(text, num_merges)

        probe = "the quick fox over the dog"
        assert fast.encode(probe) == naive.encode(probe), "Encoding differs"


# ---------------------------------------------------------------------------
# Edge-case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tricky inputs: overlapping pairs, degenerate inputs."""

    def test_overlapping_triple(self):
        """'aaa' — merge (a,a) must give [256, 97] matching naive L-to-R."""
        text = "aaa " * 100
        naive = NaiveBPETrainer()
        fast = FastBPETrainer()

        nm = naive.train(text, 5)
        fm = fast.train(text, 5)

        for i, (n, f) in enumerate(zip(nm, fm)):
            assert n == f, f"Merge {i} differs: naive={n}, fast={f}"
        assert naive.encode("aaa") == fast.encode("aaa")

    def test_overlapping_quad(self):
        """'aaaa' — merge (a,a) should give [256, 256]."""
        text = "aaaa " * 100
        naive = NaiveBPETrainer()
        fast = FastBPETrainer()

        nm = naive.train(text, 5)
        fm = fast.train(text, 5)

        for i, (n, f) in enumerate(zip(nm, fm)):
            assert n == f, f"Merge {i} differs: naive={n}, fast={f}"

    def test_overlapping_five(self):
        """'aaaaa' — tricky overlapping with remainder."""
        text = "aaaaa " * 100
        naive = NaiveBPETrainer()
        fast = FastBPETrainer()

        nm = naive.train(text, 5)
        fm = fast.train(text, 5)

        for i, (n, f) in enumerate(zip(nm, fm)):
            assert n == f, f"Merge {i} differs: naive={n}, fast={f}"
        assert naive.encode("aaaaa") == fast.encode("aaaaa")

    def test_empty_text(self):
        fast = FastBPETrainer()
        assert fast.train("", 10) == []

    def test_single_char(self):
        fast = FastBPETrainer()
        assert fast.train("a", 10) == []

    def test_zero_merges(self):
        fast = FastBPETrainer()
        assert fast.train("hello world", 0) == []


# ---------------------------------------------------------------------------
# Performance test
# ---------------------------------------------------------------------------

class TestPerformance:
    """Optimized trainer must meet wall-clock budget."""

    def test_training_speed(self):
        with open("/app/data/corpus.txt") as fh:
            text = fh.read()

        fast = FastBPETrainer()
        start = time.time()
        fast.train(text, 500)
        elapsed = time.time() - start

        assert elapsed < 30, (
            f"Training took {elapsed:.1f}s, must complete within 30s"
        )
