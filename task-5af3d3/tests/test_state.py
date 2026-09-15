"""Tests for the wavelet-tree range query engine and CSA space evaluator task."""

import json
import os
import random
from collections import Counter

import pytest


# ---- Data regeneration (same seeds as generate_data.py) ----

def generate_sequence():
    random.seed(42)
    return [random.randint(0, 511) for _ in range(50000)]


def generate_corpus():
    random.seed(1337)
    alphabet = "abcdefghijklmnopqrstuvwxyz "
    return "".join(random.choice(alphabet) for _ in range(30000))


# ---- Reference implementations ----

def compute_range_answer(seq, query):
    parts = query.split()
    qtype = parts[0]
    if qtype == "QUANTILE":
        l, r, k = int(parts[1]), int(parts[2]), int(parts[3])
        return sorted(seq[l:r])[k]
    elif qtype == "DISTINCT":
        l, r = int(parts[1]), int(parts[2])
        return len(set(seq[l:r]))
    elif qtype == "TOPFREQ":
        l, r = int(parts[1]), int(parts[2])
        counter = Counter(seq[l:r])
        max_freq = max(counter.values())
        return min(v for v, f in counter.items() if f == max_freq)
    elif qtype == "PREVVAL":
        l, r, v = int(parts[1]), int(parts[2]), int(parts[3])
        candidates = [x for x in seq[l:r] if x <= v]
        return max(candidates) if candidates else -1
    elif qtype == "NEXTVAL":
        l, r, v = int(parts[1]), int(parts[2]), int(parts[3])
        candidates = [x for x in seq[l:r] if x >= v]
        return min(candidates) if candidates else -1
    return None


def count_all_occurrences(text, pattern):
    count = 0
    start = 0
    while True:
        pos = text.find(pattern, start)
        if pos == -1:
            break
        count += 1
        start = pos + 1
    return count


def locate_all_occurrences(text, pattern, limit):
    positions = []
    start = 0
    while True:
        pos = text.find(pattern, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1
    return sorted(positions)[:limit]


# ---- Fixtures ----

@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def sequence():
    return generate_sequence()


@pytest.fixture(scope="session")
def corpus():
    return generate_corpus()


@pytest.fixture(scope="session")
def range_queries():
    with open("/app/range_queries.txt") as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture(scope="session")
def text_queries():
    with open("/app/text_queries.txt") as f:
        return [line.strip() for line in f if line.strip()]


# ---- Structure tests ----

class TestResultsStructure:
    def test_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_has_range_results(self, results):
        assert "range_results" in results

    def test_has_text_count_results(self, results):
        assert "text_count_results" in results

    def test_has_text_locate_results(self, results):
        assert "text_locate_results" in results

    def test_has_space_analysis(self, results):
        assert "space_analysis" in results

    def test_range_results_length(self, results, range_queries):
        assert len(results["range_results"]) == len(range_queries), (
            f"Expected {len(range_queries)} range_results, got {len(results['range_results'])}"
        )

    def test_text_count_length(self, results):
        assert len(results["text_count_results"]) == 8

    def test_text_locate_length(self, results):
        assert len(results["text_locate_results"]) == 5


# ---- QUANTILE tests (indices 0-7) ----

class TestQuantile:
    @pytest.mark.parametrize("idx", range(8))
    def test_quantile(self, results, sequence, range_queries, idx):
        query = range_queries[idx]
        expected = compute_range_answer(sequence, query)
        actual = results["range_results"][idx]
        assert actual == expected, f"Query '{query}': expected {expected}, got {actual}"


# ---- DISTINCT tests (indices 8-12) ----

class TestDistinct:
    @pytest.mark.parametrize("idx", range(8, 13))
    def test_distinct(self, results, sequence, range_queries, idx):
        query = range_queries[idx]
        expected = compute_range_answer(sequence, query)
        actual = results["range_results"][idx]
        assert actual == expected, f"Query '{query}': expected {expected}, got {actual}"


# ---- TOPFREQ tests (indices 13-17) ----

class TestTopFreq:
    @pytest.mark.parametrize("idx", range(13, 18))
    def test_topfreq(self, results, sequence, range_queries, idx):
        query = range_queries[idx]
        expected = compute_range_answer(sequence, query)
        actual = results["range_results"][idx]
        assert actual == expected, f"Query '{query}': expected {expected}, got {actual}"


# ---- PREVVAL tests (indices 18-22) ----

class TestPrevVal:
    @pytest.mark.parametrize("idx", range(18, 23))
    def test_prevval(self, results, sequence, range_queries, idx):
        query = range_queries[idx]
        expected = compute_range_answer(sequence, query)
        actual = results["range_results"][idx]
        assert actual == expected, f"Query '{query}': expected {expected}, got {actual}"


# ---- NEXTVAL tests (indices 23-27) ----

class TestNextVal:
    @pytest.mark.parametrize("idx", range(23, 28))
    def test_nextval(self, results, sequence, range_queries, idx):
        query = range_queries[idx]
        expected = compute_range_answer(sequence, query)
        actual = results["range_results"][idx]
        assert actual == expected, f"Query '{query}': expected {expected}, got {actual}"


# ---- Text COUNT tests ----

class TestTextCount:
    @pytest.mark.parametrize("idx", range(8))
    def test_count(self, results, corpus, text_queries, idx):
        query = text_queries[idx]
        pattern = query[6:]  # after "COUNT "
        expected = count_all_occurrences(corpus, pattern)
        actual = results["text_count_results"][idx]
        assert actual == expected, f"COUNT '{pattern}': expected {expected}, got {actual}"


# ---- Text LOCATE tests ----

class TestTextLocate:
    @pytest.mark.parametrize("idx", range(5))
    def test_locate(self, results, corpus, text_queries, idx):
        query = text_queries[8 + idx]
        parts = query.split()
        pattern = parts[1]
        k = int(parts[2])
        expected = locate_all_occurrences(corpus, pattern, k)
        actual = results["text_locate_results"][idx]
        assert actual == expected, (
            f"LOCATE '{pattern}' k={k}: expected first 5={expected[:5]}, got first 5={actual[:5]}"
        )


# ---- Space analysis tests ----

class TestSpaceAnalysis:
    def test_space_keys_present(self, results):
        space = results["space_analysis"]
        for key in [
            "wt_bit_vector", "wt_rrr_63", "wt_rrr_15",
            "csa_wt_huff", "csa_sada", "csa_bitcompressed",
            "smallest_wt", "smallest_csa",
        ]:
            assert key in space, f"Missing space_analysis key '{key}'"

    def test_wt_sizes_positive(self, results):
        space = results["space_analysis"]
        for key in ["wt_bit_vector", "wt_rrr_63", "wt_rrr_15"]:
            assert isinstance(space[key], int) and space[key] > 0, (
                f"space_analysis['{key}'] must be a positive integer, got {space[key]}"
            )

    def test_csa_sizes_positive(self, results):
        space = results["space_analysis"]
        for key in ["csa_wt_huff", "csa_sada", "csa_bitcompressed"]:
            assert isinstance(space[key], int) and space[key] > 0, (
                f"space_analysis['{key}'] must be a positive integer, got {space[key]}"
            )

    def test_smallest_wt_correct(self, results):
        space = results["space_analysis"]
        wt_sizes = {
            "wt_bit_vector": space["wt_bit_vector"],
            "wt_rrr_63": space["wt_rrr_63"],
            "wt_rrr_15": space["wt_rrr_15"],
        }
        actual_smallest = min(wt_sizes, key=wt_sizes.get)
        assert space["smallest_wt"] == actual_smallest, (
            f"smallest_wt should be '{actual_smallest}' ({wt_sizes[actual_smallest]} bytes), "
            f"but got '{space['smallest_wt']}'"
        )

    def test_smallest_csa_correct(self, results):
        space = results["space_analysis"]
        csa_sizes = {
            "csa_wt_huff": space["csa_wt_huff"],
            "csa_sada": space["csa_sada"],
            "csa_bitcompressed": space["csa_bitcompressed"],
        }
        actual_smallest = min(csa_sizes, key=csa_sizes.get)
        assert space["smallest_csa"] == actual_smallest, (
            f"smallest_csa should be '{actual_smallest}' ({csa_sizes[actual_smallest]} bytes), "
            f"but got '{space['smallest_csa']}'"
        )

    def test_bitcompressed_largest_csa(self, results):
        """For random text, uncompressed CSA should be larger than compressed variants."""
        space = results["space_analysis"]
        assert space["csa_bitcompressed"] > space["csa_wt_huff"], (
            f"csa_bitcompressed ({space['csa_bitcompressed']}) should be > "
            f"csa_wt_huff ({space['csa_wt_huff']})"
        )

    def test_wt_sizes_distinct(self, results):
        """Different bitvector types should produce different WT sizes."""
        space = results["space_analysis"]
        sizes = {space["wt_bit_vector"], space["wt_rrr_63"], space["wt_rrr_15"]}
        assert len(sizes) >= 2, (
            "Expected at least 2 distinct WT sizes across the three bitvector types"
        )
