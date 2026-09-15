"""Tests for suffix array-accelerated code search engine.

"""

import subprocess
import os
import time
import pytest

TOOL = "/app/sasearch.py"
CORPUS = "/app/corpus"
INDEX = "/tmp/test_sa_index.bin"


def run_tool(*args, timeout=120):
    """Run the search tool and return stdout, stderr, returncode."""
    cmd = ["python3", TOOL] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.stdout, result.stderr, result.returncode


def parse_results(stdout):
    """Parse search output into list of (filename, lineno, content) tuples."""
    results = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) == 3:
            results.append((parts[0], int(parts[1]), parts[2]))
    return results


@pytest.fixture(scope="session", autouse=True)
def build_index():
    """Build index once for all tests."""
    stdout, stderr, rc = run_tool("index", CORPUS, INDEX, timeout=180)
    assert rc == 0, f"Index creation failed (rc={rc}): {stderr}"
    assert os.path.exists(INDEX), "Index file was not created"
    assert os.path.getsize(INDEX) > 0, "Index file is empty"
    yield
    # Cleanup
    if os.path.exists(INDEX):
        os.remove(INDEX)


class TestLiteralSearch:
    """Test literal string search using suffix array binary search."""

    def test_unique_function_name(self):
        """Search for a function name that appears in exactly one file."""
        stdout, stderr, rc = run_tool("search", INDEX, "compute_rolling_hash")
        assert rc == 0, f"Search failed: {stderr}"
        results = parse_results(stdout)
        assert len(results) >= 1, "Should find at least one match"
        filenames = {r[0] for r in results}
        assert "algorithms.py" in filenames, "Should find match in algorithms.py"

    def test_pattern_across_multiple_files(self):
        """Search for a pattern appearing in multiple files."""
        stdout, stderr, rc = run_tool("search", INDEX, "process_batch")
        assert rc == 0
        results = parse_results(stdout)
        filenames = {r[0] for r in results}
        # "process_batch" appears in algorithms.py, data_pipeline.py, and large_dataset.txt
        assert "algorithms.py" in filenames, "Missing match in algorithms.py"
        assert "data_pipeline.py" in filenames, "Missing match in data_pipeline.py"
        assert "large_dataset.txt" in filenames, "Missing match in large_dataset.txt"

    def test_c_code_pattern(self):
        """Search for a pattern in C source code."""
        stdout, stderr, rc = run_tool("search", INDEX, "handle_client_connection")
        assert rc == 0
        results = parse_results(stdout)
        filenames = {r[0] for r in results}
        assert "networking.c" in filenames

    def test_config_file_pattern(self):
        """Search for a pattern in config file."""
        stdout, stderr, rc = run_tool("search", INDEX, "production_db")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 1
        filenames = {r[0] for r in results}
        assert "config.ini" in filenames

    def test_no_match(self):
        """Pattern that doesn't exist should return empty results."""
        stdout, stderr, rc = run_tool("search", INDEX, "xyzzy_absolutely_nonexistent_pattern_42")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) == 0, "Should find no matches for nonexistent pattern"

    def test_long_literal_phrase(self):
        """Search for a long literal phrase."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       "Process records in fixed-size batches")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 1
        assert any("algorithms.py" in r[0] for r in results)


class TestOutputFormat:
    """Test that output format is correct: filename:lineno:content."""

    def test_format_structure(self):
        """Each output line must have exactly three colon-separated fields."""
        stdout, stderr, rc = run_tool("search", INDEX, "compute_rolling_hash")
        assert rc == 0
        for line in stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(":", 2)
            assert len(parts) == 3, f"Invalid format (expected 3 parts): {line!r}"
            filename, lineno_str, content = parts
            assert lineno_str.isdigit(), f"Line number not numeric: {lineno_str!r}"
            assert int(lineno_str) > 0, f"Line number must be positive: {lineno_str}"
            assert len(filename) > 0, "Filename must not be empty"

    def test_sorted_output(self):
        """Results must be sorted by filename, then by line number."""
        stdout, stderr, rc = run_tool("search", INDEX, "process_batch")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) > 1, "Need multiple results to test sorting"

        prev_file = ""
        prev_line = 0
        for filename, lineno, content in results:
            if filename == prev_file:
                assert lineno > prev_line, \
                    f"Lines not sorted within {filename}: {lineno} should be > {prev_line}"
            else:
                assert filename >= prev_file, \
                    f"Files not sorted: {filename!r} after {prev_file!r}"
            prev_file = filename
            prev_line = lineno

    def test_no_duplicate_lines(self):
        """Same file:line should not appear more than once."""
        stdout, stderr, rc = run_tool("search", INDEX, "handle")
        assert rc == 0
        results = parse_results(stdout)
        keys = [(r[0], r[1]) for r in results]
        assert len(keys) == len(set(keys)), "Duplicate (file, line) entries in output"

    def test_line_numbers_are_one_indexed(self):
        """Line numbers should be 1-indexed."""
        stdout, stderr, rc = run_tool("search", INDEX, "Algorithm implementations")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 1
        # The docstring at the top of algorithms.py should be on line 1
        algo_results = [r for r in results if r[0] == "algorithms.py"]
        assert len(algo_results) >= 1
        assert algo_results[0][1] == 1, \
            f"First line of file should be line 1, got {algo_results[0][1]}"


class TestRegexSearch:
    """Test regex search with suffix array acceleration."""

    def test_simple_word_boundary_regex(self):
        """Regex with character class matching function names."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"handle_\w+_request", "--regex")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 3, f"Expected >=3 matches, got {len(results)}"
        filenames = {r[0] for r in results}
        assert "networking.c" in filenames

    def test_regex_alternation(self):
        """Regex with alternation operator."""
        stdout, stderr, rc = run_tool("search", INDEX, r"FIXME|TODO", "--regex")
        assert rc == 0
        results = parse_results(stdout)
        # FIXME and TODO appear in multiple files
        assert len(results) >= 6, f"Expected >=6 matches for FIXME|TODO, got {len(results)}"
        for _, _, content in results:
            assert "FIXME" in content or "TODO" in content

    def test_regex_quantifier_pattern(self):
        """Regex with quantifier and character class."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"batch_size\s*=\s*\d+", "--regex")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 2, "Should match in config.ini and data_pipeline.py"
        filenames = {r[0] for r in results}
        assert len(filenames) >= 2

    def test_regex_dot_star(self):
        """Regex with .* wildcard."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"def compute_.*checksum", "--regex")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 1
        assert any("utils.py" in r[0] for r in results)

    def test_regex_no_match(self):
        """Regex that doesn't match anything."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"zzz_impossible_\d{10}_pattern", "--regex")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) == 0


class TestCaseInsensitive:
    """Test case-insensitive search mode."""

    def test_case_insensitive_warning(self):
        """Case-insensitive search for 'warning' should find WARNING, warning, Warning."""
        stdout, stderr, rc = run_tool("search", INDEX, "warning", "--ignore-case")
        assert rc == 0
        results = parse_results(stdout)
        # WARNING appears in multiple files as comments
        assert len(results) >= 3, f"Expected >=3 case-insensitive matches, got {len(results)}"

    def test_case_insensitive_todo(self):
        """Case-insensitive 'todo' should match TODO, todo, Todo."""
        stdout, stderr, rc = run_tool("search", INDEX, "todo", "--ignore-case")
        assert rc == 0
        results = parse_results(stdout)
        # Multiple TODO/todo variants across files
        assert len(results) >= 4

    def test_case_sensitive_vs_insensitive(self):
        """Case-insensitive should return more or equal results than case-sensitive."""
        stdout_cs, _, rc1 = run_tool("search", INDEX, "WARNING")
        stdout_ci, _, rc2 = run_tool("search", INDEX, "warning", "--ignore-case")
        assert rc1 == 0 and rc2 == 0
        results_cs = parse_results(stdout_cs)
        results_ci = parse_results(stdout_ci)
        # Case-insensitive should find at least as many matches
        assert len(results_ci) >= len(results_cs), \
            f"Case-insensitive ({len(results_ci)}) should be >= case-sensitive ({len(results_cs)})"

    def test_case_insensitive_regex(self):
        """Case-insensitive regex search."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"fixme.*handle", "--regex", "--ignore-case")
        assert rc == 0
        # Should match lines containing both FIXME and handle (case-insensitive)
        results = parse_results(stdout)
        for _, _, content in results:
            lower_content = content.lower()
            assert "fixme" in lower_content


class TestRegexFactoring:
    """Test that regex factoring extracts literal components and uses SA narrowing."""

    def test_explain_shows_literal_factor(self):
        """--explain flag should output the extracted literal factor to stderr."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"compute_rolling_\w+", "--regex", "--explain")
        assert rc == 0
        assert "LITERAL_FACTOR" in stderr, \
            f"Expected LITERAL_FACTOR in stderr, got: {stderr!r}"
        # Should extract "compute_rolling_" as the literal
        assert "compute_rolling_" in stderr, \
            f"Expected 'compute_rolling_' in LITERAL_FACTOR, got: {stderr!r}"

    def test_explain_shows_candidates_and_matches(self):
        """--explain should show candidate and match counts."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"handle_\w+_request", "--regex", "--explain")
        assert rc == 0
        assert "CANDIDATES" in stderr, "Expected CANDIDATES in stderr"
        assert "MATCHES" in stderr, "Expected MATCHES in stderr"

    def test_explain_literal_factor_selection(self):
        """Regex with multiple literal segments should extract the longest."""
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"process_\w+_checkpoint", "--regex", "--explain")
        assert rc == 0
        assert "LITERAL_FACTOR" in stderr
        # Both "process_" and "_checkpoint" are literal segments
        # The tool should extract one of them (the longer is "_checkpoint" at 11 chars vs "process_" at 8)
        # Accept either as valid
        factor_line = [l for l in stderr.split("\n") if "LITERAL_FACTOR" in l]
        assert len(factor_line) >= 1
        factor_text = factor_line[0]
        assert "process_" in factor_text or "_checkpoint" in factor_text


class TestIndexPersistence:
    """Test index file properties and consistency."""

    def test_index_larger_than_corpus(self):
        """Index file must be larger than raw corpus (suffix array overhead)."""
        corpus_size = sum(
            os.path.getsize(os.path.join(CORPUS, f))
            for f in os.listdir(CORPUS)
            if os.path.isfile(os.path.join(CORPUS, f))
        )
        index_size = os.path.getsize(INDEX)
        assert index_size > corpus_size, \
            f"Index ({index_size}) should be larger than corpus ({corpus_size})"

    def test_rebuild_produces_same_results(self):
        """Rebuilding the index should produce identical search results."""
        alt_index = "/tmp/test_sa_index_alt.bin"
        try:
            stdout_build, stderr_build, rc = run_tool("index", CORPUS, alt_index, timeout=180)
            assert rc == 0, f"Alt index creation failed: {stderr_build}"

            # Compare search results from both indexes
            stdout_orig, _, _ = run_tool("search", INDEX, "compute_rolling_hash")
            stdout_alt, _, _ = run_tool("search", alt_index, "compute_rolling_hash")
            assert stdout_orig == stdout_alt, \
                "Search results differ between original and rebuilt index"

            # Also compare a regex search
            stdout_orig2, _, _ = run_tool("search", INDEX,
                                           r"handle_\w+_request", "--regex")
            stdout_alt2, _, _ = run_tool("search", alt_index,
                                          r"handle_\w+_request", "--regex")
            assert stdout_orig2 == stdout_alt2, \
                "Regex search results differ between original and rebuilt index"
        finally:
            if os.path.exists(alt_index):
                os.remove(alt_index)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_pattern(self):
        """Empty pattern should not crash."""
        stdout, stderr, rc = run_tool("search", INDEX, "")
        # Accept either empty results or a graceful error
        assert rc in (0, 1), f"Tool crashed on empty pattern (rc={rc}): {stderr}"

    def test_single_char_pattern(self):
        """Single character pattern should work."""
        stdout, stderr, rc = run_tool("search", INDEX, "#")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) > 0, "Should find comment lines with '#'"

    def test_pattern_at_line_start(self):
        """Pattern at the very start of a line."""
        stdout, stderr, rc = run_tool("search", INDEX, "import hashlib")
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) >= 1

    def test_special_characters_in_literal(self):
        """Literal search with characters that are regex metacharacters."""
        # Searching for literal "**" should not crash
        stdout, stderr, rc = run_tool("search", INDEX, "**")
        assert rc in (0, 1), f"Crashed on special chars (rc={rc}): {stderr}"

    def test_multifile_line_attribution(self):
        """Verify correct file attribution for lines near file boundaries."""
        # Search for something unique to a specific file
        stdout1, _, _ = run_tool("search", INDEX, "Rabin-Karp")
        results1 = parse_results(stdout1)
        if results1:
            assert all(r[0] == "algorithms.py" for r in results1), \
                "Rabin-Karp should only appear in algorithms.py"

        stdout2, _, _ = run_tool("search", INDEX, "INADDR_ANY")
        results2 = parse_results(stdout2)
        if results2:
            assert all(r[0] == "networking.c" for r in results2), \
                "INADDR_ANY should only appear in networking.c"


class TestPerformance:
    """Test that search completes efficiently on large corpus."""

    def test_literal_search_performance(self):
        """Literal search on large corpus must complete quickly."""
        start = time.time()
        stdout, stderr, rc = run_tool("search", INDEX,
                                       "process_batch_checkpoint", timeout=30)
        elapsed = time.time() - start
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) > 10, f"Expected >10 checkpoint matches, got {len(results)}"
        assert elapsed < 15, f"Literal search took {elapsed:.1f}s, expected <15s"

    def test_regex_search_performance(self):
        """Regex search on large corpus must complete within time limit."""
        start = time.time()
        stdout, stderr, rc = run_tool("search", INDEX,
                                       r"alpha_\w+_value", "--regex", timeout=30)
        elapsed = time.time() - start
        assert rc == 0
        results = parse_results(stdout)
        assert len(results) > 0, "Should find matches in large_dataset.txt"
        assert elapsed < 20, f"Regex search took {elapsed:.1f}s, expected <20s"
