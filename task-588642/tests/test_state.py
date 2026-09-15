"""Tests for the parametric Levenshtein DFA implementation."""


import json
import os
import sys
import pytest


def edit_distance(s1, s2):
    """Naive DP Levenshtein distance for verification."""
    m, n = len(s1), len(s2)
    if m == 0:
        return n
    if n == 0:
        return m
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if s1[i - 1] == s2[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(dp[j], dp[j - 1], prev)
            prev = temp
    return dp[n]


# ---------------------------------------------------------------------------
# Module-level tests: verify the parametric DFA implementation itself
# ---------------------------------------------------------------------------

class TestParametricDFAModule:
    """Test that the LevenshteinParametricDFA class works correctly."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, '/app')
        try:
            from parametric_dfa import LevenshteinParametricDFA
            self.PDFA = LevenshteinParametricDFA
        except Exception as e:
            pytest.fail(
                f"Could not import LevenshteinParametricDFA from "
                f"/app/parametric_dfa.py: {e}"
            )

    # --- D=1 cases ---

    def test_d1_exact_match(self):
        pdfa = self.PDFA(1)
        match, dist = pdfa.eval("hello", "hello")
        assert match is True and dist == 0

    def test_d1_substitution(self):
        pdfa = self.PDFA(1)
        match, dist = pdfa.eval("hello", "hallo")
        assert match is True and dist == 1

    def test_d1_deletion_from_query(self):
        pdfa = self.PDFA(1)
        # candidate shorter -> query char deleted
        match, dist = pdfa.eval("hello", "hell")
        assert match is True and dist == 1

    def test_d1_insertion_in_candidate(self):
        pdfa = self.PDFA(1)
        # candidate longer -> extra char in candidate
        match, dist = pdfa.eval("hello", "helloo")
        assert match is True and dist == 1

    def test_d1_rejects_two_edits(self):
        pdfa = self.PDFA(1)
        match, _ = pdfa.eval("hello", "hxxlo")
        assert match is False

    # --- D=2 cases ---

    def test_d2_two_substitutions(self):
        pdfa = self.PDFA(2)
        match, dist = pdfa.eval("hello", "hxlxo")
        assert match is True and dist == 2

    def test_d2_two_deletions(self):
        pdfa = self.PDFA(2)
        match, dist = pdfa.eval("hello", "hel")
        assert match is True and dist == 2

    def test_d2_two_insertions(self):
        pdfa = self.PDFA(2)
        match, dist = pdfa.eval("hello", "helloab")
        assert match is True and dist == 2

    def test_d2_rejects_three_edits(self):
        pdfa = self.PDFA(2)
        match, _ = pdfa.eval("hello", "he")
        assert match is False

    # --- Edge cases ---

    def test_empty_query_empty_candidate(self):
        pdfa = self.PDFA(2)
        match, dist = pdfa.eval("", "")
        assert match is True and dist == 0

    def test_empty_query_short_candidate(self):
        pdfa = self.PDFA(2)
        match, dist = pdfa.eval("", "ab")
        assert match is True and dist == 2

    def test_empty_query_too_long_candidate(self):
        pdfa = self.PDFA(2)
        match, _ = pdfa.eval("", "abc")
        assert match is False

    def test_short_query_empty_candidate(self):
        pdfa = self.PDFA(2)
        match, dist = pdfa.eval("ab", "")
        assert match is True and dist == 2

    def test_single_char_query(self):
        pdfa = self.PDFA(1)
        match, dist = pdfa.eval("a", "a")
        assert match is True and dist == 0
        match, dist = pdfa.eval("a", "b")
        assert match is True and dist == 1
        match, dist = pdfa.eval("a", "")
        assert match is True and dist == 1
        match, dist = pdfa.eval("a", "ab")
        assert match is True and dist == 1
        match, _ = pdfa.eval("a", "abc")
        assert match is False

    # --- Bulk correctness against naive ---

    def test_agrees_with_naive(self):
        """Parametric DFA must agree with naive edit distance on varied pairs."""
        pdfa2 = self.PDFA(2)
        test_pairs = [
            ("kitten", "sitting"),      # dist 3
            ("saturday", "sunday"),     # dist 3
            ("abc", "abc"),             # dist 0
            ("abc", "axc"),             # dist 1
            ("abc", "abcd"),            # dist 1
            ("abc", "ab"),              # dist 1
            ("abc", "xyz"),             # dist 3
            ("abc", "aec"),             # dist 1
            ("abc", "abcde"),           # dist 2
            ("flaw", "lawn"),           # dist 2
            ("gumbo", "gambol"),        # dist 2
            ("", ""),                   # dist 0
            ("a", ""),                  # dist 1
            ("abc", "ca"),              # dist 3
            ("book", "back"),           # dist 2
            ("algorithm", "altruistic"),# dist 6
            ("cat", "cats"),            # dist 1
            ("cats", "cat"),            # dist 1
            ("foo", "foo"),             # dist 0
            ("bar", "baz"),             # dist 1
            ("abcdef", "azced"),        # dist 3
            ("test", "tent"),           # dist 1
            ("test", "best"),           # dist 1
            ("abcd", "dcba"),           # dist 4
            ("ab", "ba"),               # dist 2
        ]
        for s1, s2 in test_pairs:
            naive_dist = edit_distance(s1, s2)
            match, dfa_dist = pdfa2.eval(s1, s2)
            if naive_dist <= 2:
                assert match is True, (
                    f"Expected match for ({s1!r}, {s2!r}), naive dist={naive_dist}"
                )
                assert dfa_dist == naive_dist, (
                    f"Wrong dist for ({s1!r}, {s2!r}): "
                    f"got {dfa_dist}, expected {naive_dist}"
                )
            else:
                assert match is False, (
                    f"Expected no match for ({s1!r}, {s2!r}), "
                    f"naive dist={naive_dist}"
                )

    # --- State count sanity ---

    def test_state_counts_reasonable(self):
        pdfa1 = self.PDFA(1)
        pdfa2 = self.PDFA(2)
        n1 = pdfa1.num_states()
        n2 = pdfa2.num_states()
        assert 3 <= n1 <= 20, (
            f"D=1 has {n1} non-dead states, expected 3-20"
        )
        assert 10 <= n2 <= 100, (
            f"D=2 has {n2} non-dead states, expected 10-100"
        )
        assert n2 > n1, "D=2 should have more states than D=1"


# ---------------------------------------------------------------------------
# Output file tests: verify the produced result files
# ---------------------------------------------------------------------------

class TestOutputFiles:
    """Test that run_queries.py produced correct outputs."""

    def test_results_file_exists(self):
        assert os.path.exists('/app/output/results.json'), \
            "/app/output/results.json not found"

    def test_dfa_stats_file_exists(self):
        assert os.path.exists('/app/output/dfa_stats.json'), \
            "/app/output/dfa_stats.json not found"

    def test_results_format(self):
        with open('/app/output/results.json') as f:
            results = json.load(f)
        assert 'query_results' in results
        assert len(results['query_results']) > 0
        for qr in results['query_results']:
            assert 'query' in qr
            assert 'max_distance' in qr
            assert 'matches' in qr
            for m in qr['matches']:
                assert 'word' in m
                assert 'distance' in m
                assert isinstance(m['distance'], int)

    def test_results_correctness(self):
        """Every reported match must be correct, and no match may be missed."""
        with open('/app/output/results.json') as f:
            results = json.load(f)
        with open('/app/dictionary.txt') as f:
            dictionary = [line.strip() for line in f if line.strip()]
        with open('/app/queries.json') as f:
            queries = json.load(f)

        # Build a lookup from query string to result entry
        result_map = {}
        for qr in results['query_results']:
            result_map[qr['query']] = qr

        for q in queries:
            query_str = q['query']
            max_d = q['max_distance']

            assert query_str in result_map, (
                f"No results found for query {query_str!r}"
            )
            qr = result_map[query_str]
            reported = {m['word']: m['distance'] for m in qr['matches']}

            # Compute ground truth
            true_matches = {}
            for word in dictionary:
                d = edit_distance(query_str, word)
                if d <= max_d:
                    true_matches[word] = d

            # No false positives
            for word, dist in reported.items():
                assert word in true_matches, (
                    f"False positive: {word!r} reported for query {query_str!r} "
                    f"(dist={dist}), true dist={edit_distance(query_str, word)}"
                )
                assert dist == true_matches[word], (
                    f"Wrong distance for {word!r} matching {query_str!r}: "
                    f"reported {dist}, true {true_matches[word]}"
                )

            # No false negatives
            for word, dist in true_matches.items():
                assert word in reported, (
                    f"False negative: {word!r} should match {query_str!r} "
                    f"(dist={dist}) but was not reported"
                )

    def test_results_sorted(self):
        """Matches must be sorted by (distance, word)."""
        with open('/app/output/results.json') as f:
            results = json.load(f)
        for qr in results['query_results']:
            matches = qr['matches']
            keys = [(m['distance'], m['word']) for m in matches]
            assert keys == sorted(keys), (
                f"Matches for {qr['query']!r} are not sorted by (distance, word)"
            )

    def test_dfa_stats_format(self):
        with open('/app/output/dfa_stats.json') as f:
            stats = json.load(f)
        assert 'd1_parametric_states' in stats
        assert 'd2_parametric_states' in stats
        assert isinstance(stats['d1_parametric_states'], int)
        assert isinstance(stats['d2_parametric_states'], int)
        assert stats['d1_parametric_states'] > 0
        assert stats['d2_parametric_states'] > stats['d1_parametric_states']
