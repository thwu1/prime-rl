
"""
Tests for the pattern matching pipeline repair task.

Verifies:
1. Aho-Corasick: dictionary suffix links, leftmost-first/longest semantics, streaming
2. Pipeline: correct error extraction, join, and aggregation from all log sources
"""

import csv
import os
import subprocess
import sys

import pytest

# Import the Aho-Corasick module from /app
sys.path.insert(0, '/app')
from aho_corasick import AhoCorasick, Match, MatchKind


# ---------------------------------------------------------------------------
# Pipeline fixture — runs pipeline.sh once before all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Execute the solver's pipeline before running any tests."""
    if os.path.exists('/app/output/results.csv'):
        os.remove('/app/output/results.csv')
    result = subprocess.run(
        ['bash', '/app/pipeline.sh'],
        capture_output=True, text=True, timeout=120,
        cwd='/app'
    )
    return result


def _read_results():
    path = '/app/output/results.csv'
    assert os.path.exists(path), (
        "results.csv not found — pipeline.sh may have failed or not been run"
    )
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


# ===========================================================================
# AHO-CORASICK TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Dictionary suffix link correctness
# ---------------------------------------------------------------------------

class TestSuffixLinks:
    """Verify that dictionary suffix links propagate outputs correctly."""

    def _classic_ac(self):
        return AhoCorasick([b"he", b"she", b"his", b"hers", b"her"])

    def test_ushers_match_count(self):
        """Standard search on 'ushers' must find 4 matches (not 3)."""
        ac = self._classic_ac()
        matches = ac.find_all(b"ushers")
        assert len(matches) == 4, (
            f"Expected 4 matches but got {len(matches)}. "
            "Dictionary suffix links may not be propagating outputs."
        )

    def test_ushers_he_found(self):
        """'he' must be found inside 'ushers' via dictionary suffix link from 'she' state."""
        ac = self._classic_ac()
        matches = ac.find_all(b"ushers")
        he_match = Match(0, 2, 4)  # pattern_id=0 ("he"), start=2, end=4
        assert he_match in matches, (
            f"Match for 'he' at (2,4) not found. Got: {matches}. "
            "The 'she' state's output must include 'he' via failure link merging."
        )

    def test_ushers_exact_matches(self):
        """Exact set of 4 matches in 'ushers'."""
        ac = self._classic_ac()
        matches = ac.find_all(b"ushers")
        expected = {
            Match(1, 1, 4),   # she
            Match(0, 2, 4),   # he (via suffix link)
            Match(4, 2, 5),   # her
            Match(3, 2, 6),   # hers
        }
        assert set(matches) == expected, (
            f"Expected {expected}, got {set(matches)}"
        )

    def test_nested_suffixes_cba(self):
        """Patterns ["a","ba","cba"] on "cba": all 3 must match at their positions."""
        ac = AhoCorasick([b"a", b"ba", b"cba"])
        matches = ac.find_all(b"cba")
        expected = {
            Match(2, 0, 3),  # cba
            Match(1, 1, 3),  # ba (suffix of cba path)
            Match(0, 2, 3),  # a  (suffix of ba path)
        }
        assert set(matches) == expected, (
            f"Expected {expected}, got {set(matches)}. "
            "Nested dictionary suffix links must chain through multiple levels."
        )

    def test_no_false_positives(self):
        """No matches when haystack contains none of the patterns."""
        ac = AhoCorasick([b"xyz", b"yz", b"z"])
        matches = ac.find_all(b"abcdef")
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# Leftmost-first (non-overlapping, first-pattern-wins)
# ---------------------------------------------------------------------------

class TestLeftmostFirst:
    """Verify leftmost-first semantics: at each position, lowest pattern_id wins."""

    def test_sam_samwise_shorter_id_wins(self):
        """["Sam","Samwise"] on "Samwise": Sam (id=0) wins over Samwise (id=1)."""
        ac = AhoCorasick([b"Sam", b"Samwise"])
        matches = ac.find_leftmost_first(b"Samwise")
        assert len(matches) == 1
        assert matches[0] == Match(0, 0, 3), (
            f"Expected Sam(0,0,3) but got {matches[0]}. "
            "Leftmost-first must pick the pattern with the lowest ID."
        )

    def test_hershey_he_then_she(self):
        """On "hershey": he (id=0) wins at pos 0, then she at pos 3."""
        ac = AhoCorasick([b"he", b"she", b"his", b"hers", b"her"])
        matches = ac.find_leftmost_first(b"hershey")
        assert len(matches) == 2
        assert matches[0] == Match(0, 0, 2), (
            f"Expected he(0,0,2) at pos 0 but got {matches[0]}"
        )
        assert matches[1] == Match(1, 3, 6), (
            f"Expected she(1,3,6) at pos 3 but got {matches[1]}"
        )

    def test_abcab_two_matches(self):
        """["ab","abcab"] on "abcab": ab(0,2) then ab(3,5) → 2 matches."""
        ac = AhoCorasick([b"ab", b"abcab"])
        matches = ac.find_leftmost_first(b"abcab")
        assert len(matches) == 2, (
            f"Expected 2 leftmost-first matches but got {len(matches)}"
        )


# ---------------------------------------------------------------------------
# Leftmost-longest (non-overlapping, longest-match-wins)
# ---------------------------------------------------------------------------

class TestLeftmostLongest:
    """Verify leftmost-longest semantics: at each position, longest match wins."""

    def test_sam_samwise_longer_wins(self):
        """["Sam","Samwise"] on "Samwise": Samwise (longer) wins over Sam."""
        ac = AhoCorasick([b"Sam", b"Samwise"])
        matches = ac.find_leftmost_longest(b"Samwise")
        assert len(matches) == 1
        assert matches[0] == Match(1, 0, 7), (
            f"Expected Samwise(1,0,7) but got {matches[0]}. "
            "Leftmost-longest must pick the longest match."
        )

    def test_hershey_hers_then_he(self):
        """On "hershey": hers (longest, len=4) at pos 0, then he at pos 4."""
        ac = AhoCorasick([b"he", b"she", b"his", b"hers", b"her"])
        matches = ac.find_leftmost_longest(b"hershey")
        assert len(matches) == 2
        assert matches[0] == Match(3, 0, 4), (
            f"Expected hers(3,0,4) at pos 0 but got {matches[0]}"
        )
        assert matches[1] == Match(0, 4, 6), (
            f"Expected he(0,4,6) at pos 4 but got {matches[1]}"
        )

    def test_abcab_one_match(self):
        """["ab","abcab"] on "abcab": abcab(0,5) covers everything → 1 match.
        This differs from leftmost-first which produces 2 matches."""
        ac = AhoCorasick([b"ab", b"abcab"])
        matches = ac.find_leftmost_longest(b"abcab")
        assert len(matches) == 1, (
            f"Expected 1 leftmost-longest match but got {len(matches)}. "
            "The longer 'abcab' at pos 0 should suppress the 'ab' at pos 3."
        )


# ---------------------------------------------------------------------------
# Streaming search (stateful across chunk boundaries)
# ---------------------------------------------------------------------------

class TestStreaming:
    """Verify that streaming search maintains state across chunks."""

    def test_matches_monolithic(self):
        """Chunked ["ush","ers"] must produce same matches as monolithic "ushers"."""
        ac = AhoCorasick([b"he", b"she", b"his", b"hers", b"her"])
        monolithic = ac.find_all(b"ushers")
        streamed = ac.find_streaming([b"ush", b"ers"])
        assert set(streamed) == set(monolithic), (
            f"Streaming produced {set(streamed)} but monolithic produced {set(monolithic)}"
        )

    def test_cross_chunk_boundary(self):
        """Pattern 'abcde' spanning chunks ['abc','defg'] must be found."""
        ac = AhoCorasick([b"abcde"])
        matches = ac.find_streaming([b"abc", b"defg"])
        assert len(matches) == 1
        assert matches[0] == Match(0, 0, 5), (
            f"Expected abcde(0,0,5) but got {matches}"
        )

    def test_streaming_with_leftmost_first(self):
        """Streaming with LEFTMOST_FIRST on ["ush","ers"] → 1 match (she only)."""
        ac = AhoCorasick([b"he", b"she", b"his", b"hers", b"her"])
        matches = ac.find_streaming(
            [b"ush", b"ers"], match_kind=MatchKind.LEFTMOST_FIRST
        )
        assert len(matches) == 1
        assert matches[0] == Match(1, 1, 4), (
            f"Expected she(1,1,4) but got {matches}"
        )


# ===========================================================================
# PIPELINE TESTS
# ===========================================================================

# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

class TestPipelineExecution:

    def test_pipeline_exits_successfully(self, run_pipeline):
        assert run_pipeline.returncode == 0, (
            f"pipeline.sh exited with code {run_pipeline.returncode}\n"
            f"stderr: {run_pipeline.stderr}"
        )

    def test_output_file_created(self):
        assert os.path.exists('/app/output/results.csv')


# ---------------------------------------------------------------------------
# Result structure and counts
# ---------------------------------------------------------------------------

class TestPipelineResults:

    def test_all_error_codes_present(self):
        """All 6 error codes (E001-E006) must appear in results."""
        rows = _read_results()
        codes = {r['error_code'] for r in rows}
        assert codes == {'E001', 'E002', 'E003', 'E004', 'E005', 'E006'}, (
            f"Expected all codes E001-E006, got {sorted(codes)}"
        )

    def test_exactly_six_rows(self):
        rows = _read_results()
        assert len(rows) == 6

    def test_total_event_count(self):
        """Sum of all counts should be exactly 16."""
        rows = _read_results()
        total = sum(int(r['count']) for r in rows)
        assert total == 16, f"Total is {total}, expected 16"

    def test_e001_count(self):
        """E001: 3 (access) + 1 (exceptions) + 1 (binary) + 1 (app_events) = 6"""
        rows = _read_results()
        e001 = next(r for r in rows if r['error_code'] == 'E001')
        assert int(e001['count']) == 6

    def test_e002_count(self):
        """E002: 1 (access) + 1 (binary) = 2"""
        rows = _read_results()
        e002 = next(r for r in rows if r['error_code'] == 'E002')
        assert int(e002['count']) == 2

    def test_e003_count(self):
        """E003: 2 (access) + 1 (.app_errors) = 3"""
        rows = _read_results()
        e003 = next(r for r in rows if r['error_code'] == 'E003')
        assert int(e003['count']) == 3

    def test_e004_count(self):
        """E004: 1 (access) + 1 (app_events) = 2"""
        rows = _read_results()
        e004 = next(r for r in rows if r['error_code'] == 'E004')
        assert int(e004['count']) == 2

    def test_e005_count(self):
        """E005: 2 (exceptions, multiline entries) = 2"""
        rows = _read_results()
        e005 = next(r for r in rows if r['error_code'] == 'E005')
        assert int(e005['count']) == 2

    def test_e006_count(self):
        """E006: 1 (.app_errors) = 1"""
        rows = _read_results()
        e006 = next(r for r in rows if r['error_code'] == 'E006')
        assert int(e006['count']) == 1

    def test_e004_message_not_overcaptured(self):
        """Greedy quantifier must not capture beyond the first closing quote."""
        rows = _read_results()
        e004 = next(r for r in rows if r['error_code'] == 'E004')
        first_msg = e004.get('first_message', '')
        assert 'user=' not in first_msg, (
            f"E004 first_message appears overcaptured: '{first_msg}'"
        )
        assert first_msg == 'Authentication failed', (
            f"E004 first_message is '{first_msg}', expected 'Authentication failed'"
        )

    def test_categories(self):
        rows = _read_results()
        cats = {r['error_code']: r['category'] for r in rows}
        assert cats['E001'] == 'network'
        assert cats['E003'] == 'storage'
        assert cats['E004'] == 'auth'
        assert cats['E005'] == 'application'
        assert cats['E006'] == 'memory'

    def test_severities(self):
        rows = _read_results()
        sevs = {r['error_code']: r['severity'] for r in rows}
        assert sevs['E001'] == 'critical'
        assert sevs['E002'] == 'warning'
        assert sevs['E004'] == 'high'
        assert sevs['E005'] == 'critical'
