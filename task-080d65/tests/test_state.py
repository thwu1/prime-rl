
import sys
import os
import json
import struct
import itertools
sys.path.insert(0, "/app")

import pytest


# ---------------------------------------------------------------------------
# Reference naive Levenshtein for oracle comparisons
# ---------------------------------------------------------------------------

def _naive_levenshtein(s1, s2):
    """Standard DP edit distance."""
    if len(s1) < len(s2):
        return _naive_levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(
                prev[j + 1] + 1,      # deletion
                curr[j] + 1,           # insertion
                prev[j] + (c1 != c2),  # substitution
            ))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Test: ConcreteDFA correctness vs naive edit distance
# ---------------------------------------------------------------------------

class TestConcreteDFACorrectnessD1:
    """Build concrete DFAs for D=1 and verify accept/reject against naive."""

    QUERIES = ["cat", "dog", "hello", "a", "", "abcde", "zzz"]
    TEST_STRINGS = [
        "", "a", "ab", "cat", "bat", "ca", "cats", "caat", "ct",
        "dog", "do", "dogs", "dg", "dig", "hello", "helo", "hell",
        "helloo", "hllo", "jello", "xyz", "abcde", "abcdf", "abcd",
        "abcdef", "zzz", "zz", "zzzz", "azz", "zzza",
    ]

    def test_all_pairs(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(1)
        for query in self.QUERIES:
            dfa = pdfa.build_dfa(query)
            for test in self.TEST_STRINGS:
                expected = _naive_levenshtein(query, test) <= 1
                state = dfa.initial_state
                for ch in test:
                    state = dfa.step(state, ch)
                    if state is None:
                        break
                actual = state is not None and dfa.is_match(state)
                assert actual == expected, (
                    f"D=1 query={query!r} test={test!r}: "
                    f"DFA says {actual}, expected {expected} "
                    f"(dist={_naive_levenshtein(query, test)})"
                )


class TestConcreteDFACorrectnessD2:
    """Same for D=2."""

    QUERIES = ["kitten", "abc", "", "xy", "hello"]
    TEST_STRINGS = [
        "", "a", "ab", "abc", "abcd", "abcde", "abd", "aec", "bc",
        "ac", "xyz", "xy", "x", "xyza", "xyzab", "kitten", "sitting",
        "kiten", "kittn", "kit", "kittens", "mitten", "bitten",
        "hello", "helo", "hllo", "hell", "helloo", "jello", "he",
        "hellooo", "yellow", "ello",
    ]

    def test_all_pairs(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(2)
        for query in self.QUERIES:
            dfa = pdfa.build_dfa(query)
            for test in self.TEST_STRINGS:
                expected = _naive_levenshtein(query, test) <= 2
                state = dfa.initial_state
                for ch in test:
                    state = dfa.step(state, ch)
                    if state is None:
                        break
                actual = state is not None and dfa.is_match(state)
                assert actual == expected, (
                    f"D=2 query={query!r} test={test!r}: "
                    f"DFA says {actual}, expected {expected} "
                    f"(dist={_naive_levenshtein(query, test)})"
                )


class TestConcreteDFADistance:
    """Verify that distance() returns the correct minimum edit distance."""

    def test_distances_d2(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(2)
        query = "abc"
        tests = ["abc", "ab", "abcd", "axc", "axx", "xbc", "a", "abcde", "xyz"]
        dfa = pdfa.build_dfa(query)
        for test in tests:
            state = dfa.initial_state
            for ch in test:
                state = dfa.step(state, ch)
                if state is None:
                    break
            if state is not None and dfa.is_match(state):
                got_dist = dfa.distance(state)
                expected_dist = _naive_levenshtein(query, test)
                assert got_dist == expected_dist, (
                    f"query={query!r} test={test!r}: "
                    f"distance()={got_dist}, expected {expected_dist}"
                )


# ---------------------------------------------------------------------------
# Test: Exhaustive short-string verification
# ---------------------------------------------------------------------------

class TestExhaustiveShortStrings:
    """Exhaustively test all strings up to length 4 over alphabet {a,b,c}."""

    def _gen_strings(self, max_len, alphabet="abc"):
        for length in range(max_len + 1):
            for chars in itertools.product(alphabet, repeat=length):
                yield "".join(chars)

    def test_exhaustive_d1(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(1)
        queries = ["ab", "ba", "aaa", "c", ""]
        all_strings = list(self._gen_strings(4))
        for query in queries:
            dfa = pdfa.build_dfa(query)
            for test in all_strings:
                expected = _naive_levenshtein(query, test) <= 1
                state = dfa.initial_state
                for ch in test:
                    state = dfa.step(state, ch)
                    if state is None:
                        break
                actual = state is not None and dfa.is_match(state)
                assert actual == expected, (
                    f"Exhaustive D=1 query={query!r} test={test!r}: "
                    f"DFA={actual} expected={expected}"
                )

    def test_exhaustive_d2(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(2)
        queries = ["ab", "cc", ""]
        all_strings = list(self._gen_strings(4))
        for query in queries:
            dfa = pdfa.build_dfa(query)
            for test in all_strings:
                expected = _naive_levenshtein(query, test) <= 2
                state = dfa.initial_state
                for ch in test:
                    state = dfa.step(state, ch)
                    if state is None:
                        break
                actual = state is not None and dfa.is_match(state)
                assert actual == expected, (
                    f"Exhaustive D=2 query={query!r} test={test!r}: "
                    f"DFA={actual} expected={expected}"
                )


# ---------------------------------------------------------------------------
# Test: FuzzySearcher
# ---------------------------------------------------------------------------

class TestFuzzySearcher:
    DICTIONARY = [
        "apple", "application", "apply", "ape", "maple",
        "cat", "car", "cart", "card", "care", "scar",
        "hello", "halo", "help", "helm", "hero",
        "world", "word", "worm", "worn", "work",
        "test", "text", "best", "rest", "nest",
    ]

    def test_exact_match(self):
        from levenshtein_dfa import ParametricDFA, FuzzySearcher
        pdfa = ParametricDFA(1)
        searcher = FuzzySearcher(self.DICTIONARY)
        results = searcher.search(pdfa, "hello")
        words = [w for w, d in results]
        assert "hello" in words
        for w, d in results:
            if w == "hello":
                assert d == 0

    def test_d1_fuzzy(self):
        from levenshtein_dfa import ParametricDFA, FuzzySearcher
        pdfa = ParametricDFA(1)
        searcher = FuzzySearcher(self.DICTIONARY)
        results = searcher.search(pdfa, "cat")
        words = {w for w, d in results}
        assert "cat" in words
        assert "car" in words
        assert "cart" in words
        assert "card" not in words

    def test_d2_fuzzy(self):
        from levenshtein_dfa import ParametricDFA, FuzzySearcher
        pdfa = ParametricDFA(2)
        searcher = FuzzySearcher(self.DICTIONARY)
        results = searcher.search(pdfa, "cat")
        words = {w for w, d in results}
        assert "card" in words
        assert "care" in words
        assert "scar" in words
        assert "apple" not in words

    def test_results_sorted(self):
        from levenshtein_dfa import ParametricDFA, FuzzySearcher
        pdfa = ParametricDFA(2)
        searcher = FuzzySearcher(self.DICTIONARY)
        results = searcher.search(pdfa, "word")
        assert results == sorted(results)

    def test_distances_correct(self):
        from levenshtein_dfa import ParametricDFA, FuzzySearcher
        pdfa = ParametricDFA(2)
        searcher = FuzzySearcher(self.DICTIONARY)
        results = searcher.search(pdfa, "test")
        for word, dist in results:
            expected = _naive_levenshtein("test", word)
            assert dist == expected, (
                f"FuzzySearcher: word={word!r} dist={dist} expected={expected}"
            )

    def test_empty_query(self):
        from levenshtein_dfa import ParametricDFA, FuzzySearcher
        pdfa = ParametricDFA(2)
        searcher = FuzzySearcher(self.DICTIONARY)
        results = searcher.search(pdfa, "")
        for word, dist in results:
            assert len(word) <= 2


# ---------------------------------------------------------------------------
# Test: Bitpacking round-trip
# ---------------------------------------------------------------------------

class TestBitpacking:

    def test_roundtrip_simple(self):
        from levenshtein_dfa import bitpack_postings, unpack_postings
        doc_ids = [1, 3, 7, 8, 13, 42, 100, 200]
        packed = bitpack_postings(doc_ids)
        assert isinstance(packed, (bytes, bytearray))
        unpacked = unpack_postings(packed)
        assert unpacked == doc_ids

    def test_roundtrip_exact_block(self):
        from levenshtein_dfa import bitpack_postings, unpack_postings
        doc_ids = list(range(1, 33))
        packed = bitpack_postings(doc_ids)
        unpacked = unpack_postings(packed)
        assert unpacked == doc_ids

    def test_roundtrip_multiple_blocks(self):
        from levenshtein_dfa import bitpack_postings, unpack_postings
        doc_ids = sorted(set(i * 7 + i % 3 for i in range(100)))
        packed = bitpack_postings(doc_ids)
        unpacked = unpack_postings(packed)
        assert unpacked == doc_ids

    def test_roundtrip_large_gaps(self):
        from levenshtein_dfa import bitpack_postings, unpack_postings
        doc_ids = [10, 10000, 100000, 1000000, 2000000000]
        packed = bitpack_postings(doc_ids)
        unpacked = unpack_postings(packed)
        assert unpacked == doc_ids

    def test_roundtrip_single_element(self):
        from levenshtein_dfa import bitpack_postings, unpack_postings
        doc_ids = [42]
        packed = bitpack_postings(doc_ids)
        unpacked = unpack_postings(packed)
        assert unpacked == doc_ids

    def test_compression_ratio(self):
        from levenshtein_dfa import bitpack_postings
        doc_ids = list(range(1, 129))
        packed = bitpack_postings(doc_ids)
        raw_size = len(doc_ids) * 4
        assert len(packed) < raw_size, (
            f"Packed size {len(packed)} should be < raw size {raw_size}"
        )

    def test_empty_input(self):
        from levenshtein_dfa import bitpack_postings, unpack_postings
        packed = bitpack_postings([])
        unpacked = unpack_postings(packed)
        assert unpacked == []


# ---------------------------------------------------------------------------
# Test: DFA reuse across queries (parametric property)
# ---------------------------------------------------------------------------

class TestParametricReuse:
    """The same ParametricDFA object must work correctly for multiple queries."""

    def test_reuse_d1(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(1)
        queries = ["hello", "world", "foo", "bar", "a", "abcdefgh"]
        tests = ["hello", "world", "helo", "worl", "fo", "baz", "b", "abcdefg"]
        for query in queries:
            dfa = pdfa.build_dfa(query)
            for test in tests:
                expected = _naive_levenshtein(query, test) <= 1
                state = dfa.initial_state
                for ch in test:
                    state = dfa.step(state, ch)
                    if state is None:
                        break
                actual = state is not None and dfa.is_match(state)
                assert actual == expected

    def test_reuse_d2(self):
        from levenshtein_dfa import ParametricDFA
        pdfa = ParametricDFA(2)
        queries = ["search", "engine", "rust"]
        tests = ["serch", "engin", "rast", "rusty", "surch", "trust", "se", "eng"]
        for query in queries:
            dfa = pdfa.build_dfa(query)
            for test in tests:
                expected = _naive_levenshtein(query, test) <= 2
                state = dfa.initial_state
                for ch in test:
                    state = dfa.step(state, ch)
                    if state is None:
                        break
                actual = state is not None and dfa.is_match(state)
                assert actual == expected


# ---------------------------------------------------------------------------
# Test: Binary format compatibility with reference files
# ---------------------------------------------------------------------------

class TestBinaryCompatibility:
    """Verify byte-exact match with reference binary files."""

    def test_small_postings_match(self):
        from levenshtein_dfa import bitpack_postings
        with open("/app/data/postings_small.json") as f:
            doc_ids = json.load(f)
        with open("/app/data/postings_small.bin", "rb") as f:
            reference = f.read()
        actual = bitpack_postings(doc_ids)
        assert actual == reference, (
            f"Small postings: output ({len(actual)} bytes) differs from "
            f"reference ({len(reference)} bytes). Use xxd to compare."
        )

    def test_block_postings_match(self):
        from levenshtein_dfa import bitpack_postings
        with open("/app/data/postings_block.json") as f:
            doc_ids = json.load(f)
        with open("/app/data/postings_block.bin", "rb") as f:
            reference = f.read()
        actual = bitpack_postings(doc_ids)
        assert actual == reference, (
            f"Block postings: output ({len(actual)} bytes) differs from "
            f"reference ({len(reference)} bytes). Use xxd to compare."
        )

    def test_mixed_postings_match(self):
        from levenshtein_dfa import bitpack_postings
        with open("/app/data/postings_mixed.json") as f:
            doc_ids = json.load(f)
        with open("/app/data/postings_mixed.bin", "rb") as f:
            reference = f.read()
        actual = bitpack_postings(doc_ids)
        assert actual == reference, (
            f"Mixed postings: output ({len(actual)} bytes) differs from "
            f"reference ({len(reference)} bytes). Use xxd to compare."
        )


# ---------------------------------------------------------------------------
# Test: Format specification document
# ---------------------------------------------------------------------------

class TestFormatSpecification:
    """Verify the format spec is correct and complete."""

    def test_spec_exists(self):
        assert os.path.exists("/app/format_spec.txt"), \
            "format_spec.txt not found at /app/format_spec.txt"

    def test_spec_documents_byte_order(self):
        with open("/app/format_spec.txt") as f:
            content = f.read().lower()
        assert "little" in content and "endian" in content, \
            "Format spec must document little-endian byte order"

    def test_spec_documents_delta_encoding(self):
        with open("/app/format_spec.txt") as f:
            content = f.read().lower()
        assert "delta" in content, \
            "Format spec must document delta encoding"

    def test_spec_documents_block_structure(self):
        with open("/app/format_spec.txt") as f:
            content = f.read().lower()
        assert "32" in content, \
            "Format spec must document the block size of 32"
        has_bit_packing = ("bit" in content and
                           ("width" in content or "pack" in content))
        assert has_bit_packing, \
            "Format spec must document bit-width/bitpacking"

    def test_spec_documents_header(self):
        with open("/app/format_spec.txt") as f:
            content = f.read().lower()
        has_header_info = ("count" in content or "header" in content
                           or "length" in content or "number" in content)
        assert has_header_info, \
            "Format spec must document the count/length header"

    def test_spec_minimum_length(self):
        with open("/app/format_spec.txt") as f:
            content = f.read()
        assert len(content) >= 200, \
            f"Format spec too short ({len(content)} chars), expected >= 200"


# ---------------------------------------------------------------------------
# Test: Benchmark report
# ---------------------------------------------------------------------------

class TestBenchmarkReport:
    """Verify the performance benchmark report is valid and complete."""

    def test_report_exists(self):
        assert os.path.exists("/app/benchmark_report.json"), \
            "benchmark_report.json not found at /app/benchmark_report.json"

    def test_report_is_valid_json(self):
        with open("/app/benchmark_report.json") as f:
            report = json.load(f)
        assert isinstance(report, dict)

    def test_report_has_timing_fields(self):
        with open("/app/benchmark_report.json") as f:
            report = json.load(f)
        assert "dfa_mean_ms" in report, "Missing dfa_mean_ms"
        assert "naive_mean_ms" in report, "Missing naive_mean_ms"
        assert isinstance(report["dfa_mean_ms"], (int, float))
        assert isinstance(report["naive_mean_ms"], (int, float))
        assert report["dfa_mean_ms"] > 0, "dfa_mean_ms must be positive"
        assert report["naive_mean_ms"] > 0, "naive_mean_ms must be positive"

    def test_report_has_speedup(self):
        with open("/app/benchmark_report.json") as f:
            report = json.load(f)
        assert "speedup_factor" in report, "Missing speedup_factor"
        assert isinstance(report["speedup_factor"], (int, float))
        assert report["speedup_factor"] > 1.0, \
            f"DFA should be faster than naive (speedup={report['speedup_factor']})"

    def test_report_has_recommendation(self):
        with open("/app/benchmark_report.json") as f:
            report = json.load(f)
        assert "recommendation" in report, "Missing recommendation"
        assert isinstance(report["recommendation"], str)
        assert len(report["recommendation"]) >= 30, \
            "Recommendation should be substantive (>= 30 chars)"
