
import json
import sys
import time

import pytest

sys.path.insert(0, "/app")
from reference import NaiveBPETrainer


def load_fast_trainer():
    from fast_bpe import FastBPETrainer
    return FastBPETrainer()


def load_reference_merges(path):
    with open(path) as f:
        data = json.load(f)
    return {tuple(map(int, k.split(","))): v for k, v in data.items()}


# ---------------------------------------------------------------------------
# Small correctness tests — compare directly against naive at test time
# ---------------------------------------------------------------------------


class TestSmallCorrectness:
    """Verify merge tables match the naive reference on small inputs."""

    def _compare(self, text, num_merges):
        naive = NaiveBPETrainer()
        fast = load_fast_trainer()
        expected = naive.train(text, num_merges)
        actual = fast.train(text, num_merges)
        assert actual == expected, (
            f"Mismatch on text={text!r}, num_merges={num_merges}\n"
            f"expected={expected}\nactual={actual}"
        )

    def test_empty_string(self):
        self._compare("", 10)

    def test_single_char(self):
        self._compare("x", 10)

    def test_two_chars(self):
        self._compare("ab", 5)

    def test_wikipedia_example(self):
        """The classic BPE example: aaabdaaabac with 3 merges."""
        self._compare("aaabdaaabac", 3)

    def test_short_sentence(self):
        self._compare("hello world", 10)

    def test_repeated_word(self):
        self._compare("the the the the the", 15)

    def test_mixed_content(self):
        self._compare("abc123!@# def456", 20)

    def test_utf8_text(self):
        self._compare("café résumé naïve über", 30)

    def test_more_merges_than_possible(self):
        """Request more merges than the text can support."""
        self._compare("ab", 1000)

    def test_longer_text_many_merges(self):
        text = "the quick brown fox jumps over the lazy dog " * 10
        self._compare(text, 100)


# ---------------------------------------------------------------------------
# Edge-case tests — overlapping and repeated patterns
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test tricky overlapping-pair scenarios that break naive optimizations."""

    def _compare(self, text, num_merges):
        naive = NaiveBPETrainer()
        fast = load_fast_trainer()
        expected = naive.train(text, num_merges)
        actual = fast.train(text, num_merges)
        assert actual == expected, (
            f"Mismatch on text={text!r}, num_merges={num_merges}\n"
            f"expected={expected}\nactual={actual}"
        )

    def test_triple_same_char(self):
        """aaa: pair (a,a) count=2, but merging consumes only one occurrence."""
        self._compare("aaa", 3)

    def test_quadruple_same_char(self):
        self._compare("aaaa", 5)

    def test_quintuple_same_char(self):
        self._compare("aaaaa", 5)

    def test_long_run_same_char(self):
        self._compare("a" * 20, 15)

    def test_alternating_pair(self):
        """ababab: pair (a,b) merges all non-overlapping occurrences."""
        self._compare("ababab", 5)

    def test_alternating_triple(self):
        self._compare("abcabcabc", 10)

    def test_overlapping_then_distinct(self):
        """aaab: (a,a) merges first, creating new pair (256, a) or (256, b)."""
        self._compare("aaab", 5)

    def test_mixed_overlapping(self):
        self._compare("aabbccaabbcc", 10)

    def test_palindrome_pattern(self):
        self._compare("abcba" * 5, 15)

    def test_single_byte_repeated_many(self):
        """Stress test: long run of one byte value."""
        self._compare("x" * 100, 20)

    def test_two_byte_alternating_long(self):
        self._compare("ab" * 50, 15)

    def test_tie_breaking_order(self):
        """Pairs with equal frequency — leftmost-first must win."""
        # In 'abcd', all pairs have count 1. The first pair (a,b) must win.
        self._compare("abcd", 3)

    def test_tie_breaking_longer(self):
        """Multiple pairs tie at count=2. Leftmost pair wins."""
        # 'abcdabcd': pairs (a,b),(b,c),(c,d),(d,a) each appear twice.
        # (a,b) appears first (position 0) and must win.
        self._compare("abcdabcd", 5)


# ---------------------------------------------------------------------------
# Medium corpus — compare against precomputed reference
# ---------------------------------------------------------------------------


class TestMediumCorpus:
    def test_medium_correctness(self):
        with open("/app/corpus_medium.txt") as f:
            text = f.read()
        ref_merges = load_reference_merges("/app/reference_merges_medium.json")

        fast = load_fast_trainer()
        merges = fast.train(text, 500)

        assert len(merges) == len(ref_merges), (
            f"Expected {len(ref_merges)} merges, got {len(merges)}"
        )
        assert merges == ref_merges, "Merge table does not match reference"


# ---------------------------------------------------------------------------
# Large corpus — correctness AND performance
# ---------------------------------------------------------------------------


class TestLargeCorpus:
    def test_large_correctness_and_performance(self):
        with open("/app/corpus_large.txt") as f:
            text = f.read()
        ref_merges = load_reference_merges("/app/reference_merges_large.json")

        fast = load_fast_trainer()

        start = time.time()
        merges = fast.train(text, 2000)
        elapsed = time.time() - start

        # Correctness
        assert len(merges) == len(ref_merges), (
            f"Expected {len(ref_merges)} merges, got {len(merges)}"
        )
        assert merges == ref_merges, "Merge table does not match reference"

        # Performance: must complete well under what the naive O(N*M) takes
        assert elapsed < 120.0, (
            f"Training took {elapsed:.1f}s — must complete in under 120s. "
            f"The naive implementation cannot finish this workload in time."
        )

    def test_merge_structural_validity(self):
        """Verify structural properties of the merge table independently."""
        with open("/app/corpus_large.txt") as f:
            text = f.read()

        fast = load_fast_trainer()
        merges = fast.train(text, 2000)

        # Token IDs must be sequential starting at 256
        expected_ids = list(range(256, 256 + len(merges)))
        actual_ids = list(merges.values())
        assert actual_ids == expected_ids, "Token IDs are not sequential from 256"

        # Each merge pair must consist of previously valid token IDs
        valid_ids = set(range(256))  # raw bytes
        for (a, b), new_id in merges.items():
            assert a in valid_ids, f"Invalid left token {a} in merge {(a,b)}->{new_id}"
            assert b in valid_ids, f"Invalid right token {b} in merge {(a,b)}->{new_id}"
            valid_ids.add(new_id)
