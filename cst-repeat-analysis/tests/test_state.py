"""
Tests for compressed suffix tree analysis results.
Validates agent output at /app/results.json against a pure Python
suffix array / LCP / BWT reference computation.

"""
import json
import os
import pytest


# ── Python reference computation ──


def compute_suffix_tree_reference(corpus):
    """
    Compute expected suffix tree structural properties using pure Python.
    Mimics SDSL's construct_im(cst, text, 1) which appends a \\x00 sentinel.
    """
    text = corpus + "\x00"
    n = len(text)

    # Build suffix array via sorted suffixes
    sa = sorted(range(n), key=lambda i: text[i:])

    # Build LCP array using Kasai's algorithm
    rank = [0] * n
    for i in range(n):
        rank[sa[i]] = i
    lcp = [0] * n
    h = 0
    for i in range(n):
        if rank[i] > 0:
            j = sa[rank[i] - 1]
            while i + h < n and j + h < n and text[i + h] == text[j + h]:
                h += 1
            lcp[rank[i]] = h
            if h > 0:
                h -= 1
        else:
            h = 0

    # Build BWT
    bwt = [text[(sa[i] - 1) % n] for i in range(n)]

    # Enumerate LCP intervals (each = one internal node) using monotone stack
    intervals = []  # list of (lb, rb, depth)
    stack = [(0, 0)]  # (depth, lb) — seed with depth 0

    for i in range(1, n):
        lb = i - 1
        while stack and stack[-1][0] > lcp[i]:
            depth, saved_lb = stack.pop()
            intervals.append((saved_lb, i - 1, depth))
            lb = saved_lb
        if not stack or stack[-1][0] < lcp[i]:
            stack.append((lcp[i], lb))

    # Pop remaining entries (including root)
    while stack:
        depth, saved_lb = stack.pop()
        intervals.append((saved_lb, n - 1, depth))

    num_internal_nodes = len(intervals)
    num_leaves = n  # one leaf per suffix (including sentinel suffix)

    # Longest repeated substring: deepest internal node, lex-first on tie
    max_depth = 0
    best_lb = 0
    best_rb = 0
    for lb_v, rb_v, d in intervals:
        if d > max_depth or (d == max_depth and d > 0 and lb_v < best_lb):
            max_depth = d
            best_lb = lb_v
            best_rb = rb_v

    lrs = text[sa[best_lb] : sa[best_lb] + max_depth] if max_depth > 0 else ""
    lrs_freq = best_rb - best_lb + 1 if max_depth > 0 else 0

    # Maximal and supermaximal repeats (skip root at depth 0)
    num_maximal = 0
    num_supermaximal = 0
    for lb_v, rb_v, d in intervals:
        if d == 0:
            continue
        # Left-diversity: BWT chars at positions lb..rb have > 1 distinct value
        bwt_chars = set(bwt[lb_v : rb_v + 1])
        if len(bwt_chars) > 1:
            num_maximal += 1
            # Supermaximal: all children are leaves ⟺ no child interval exists
            # ⟺ max(lcp[lb+1 .. rb]) == depth
            if max(lcp[lb_v + 1 : rb_v + 1]) == d:
                num_supermaximal += 1

    return {
        "num_internal_nodes": num_internal_nodes,
        "num_leaves": num_leaves,
        "longest_repeat_length": max_depth,
        "longest_repeat_string": lrs,
        "longest_repeat_frequency": lrs_freq,
        "num_maximal_repeats": num_maximal,
        "num_supermaximal_repeats": num_supermaximal,
    }


def count_overlapping(text, pattern):
    """Count all occurrences of pattern in text, including overlapping."""
    count = 0
    start = 0
    while True:
        pos = text.find(pattern, start)
        if pos == -1:
            break
        count += 1
        start = pos + 1
    return count


# ── Fixtures ──


@pytest.fixture(scope="module")
def corpus():
    with open("/app/corpus.txt", "r") as f:
        return f.read()


@pytest.fixture(scope="module")
def queries():
    with open("/app/queries.txt", "r") as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture(scope="module")
def results():
    path = "/app/results.json"
    assert os.path.isfile(path), f"Agent output not found at {path}"
    with open(path, "r") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference(corpus):
    return compute_suffix_tree_reference(corpus)


# ── Pattern count tests (verified independently with Python) ──


def test_all_query_patterns_present(results, queries):
    """Every query pattern must appear in the results."""
    for q in queries:
        assert q in results["pattern_counts"], f"Missing pattern '{q}' in pattern_counts"


def test_pattern_counts_match_python(results, queries, corpus):
    """Pattern counts must match overlapping occurrence count on the corpus."""
    for q in queries:
        expected_count = count_overlapping(corpus, q)
        actual = results["pattern_counts"][q]
        assert actual == expected_count, (
            f"Pattern '{q}': expected {expected_count}, got {actual}"
        )


# ── Longest repeated substring tests ──


def test_longest_repeat_string_exists_in_corpus(results, corpus):
    """The reported LRS must actually occur at least twice in the corpus."""
    lrs = results["longest_repeat_string"]
    assert len(lrs) > 0, "LRS should be non-empty"
    occ = count_overlapping(corpus, lrs)
    assert occ >= 2, f"LRS '{lrs[:40]}...' has only {occ} occurrences (need >= 2)"


def test_longest_repeat_length_consistent(results):
    """longest_repeat_length must equal len(longest_repeat_string)."""
    assert results["longest_repeat_length"] == len(results["longest_repeat_string"])


def test_longest_repeat_length_matches_reference(results, reference):
    """LRS length must match Python reference computation."""
    assert results["longest_repeat_length"] == reference["longest_repeat_length"], (
        f"LRS length: got {results['longest_repeat_length']}, "
        f"expected {reference['longest_repeat_length']}"
    )


def test_longest_repeat_frequency_matches_reference(results, reference):
    """LRS frequency must match reference."""
    assert results["longest_repeat_frequency"] == reference["longest_repeat_frequency"], (
        f"LRS freq: got {results['longest_repeat_frequency']}, "
        f"expected {reference['longest_repeat_frequency']}"
    )


# ── Structural property tests ──


def test_num_leaves_correct(results, corpus):
    """Number of leaves = text length + 1 (including sentinel suffix)."""
    expected_leaves = len(corpus) + 1
    assert results["num_leaves"] == expected_leaves, (
        f"num_leaves: got {results['num_leaves']}, expected {expected_leaves}"
    )


def test_num_internal_nodes_matches_reference(results, reference):
    """Internal node count must match Python reference."""
    assert results["num_internal_nodes"] == reference["num_internal_nodes"], (
        f"num_internal_nodes: got {results['num_internal_nodes']}, "
        f"expected {reference['num_internal_nodes']}"
    )


def test_num_maximal_repeats_matches_reference(results, reference):
    """Maximal repeat count must match Python reference."""
    assert results["num_maximal_repeats"] == reference["num_maximal_repeats"], (
        f"num_maximal_repeats: got {results['num_maximal_repeats']}, "
        f"expected {reference['num_maximal_repeats']}"
    )


def test_num_supermaximal_repeats_matches_reference(results, reference):
    """Supermaximal repeat count must match Python reference."""
    assert results["num_supermaximal_repeats"] == reference["num_supermaximal_repeats"], (
        f"num_supermaximal_repeats: got {results['num_supermaximal_repeats']}, "
        f"expected {reference['num_supermaximal_repeats']}"
    )


# ── Space usage sanity checks ──


def test_space_bytes_positive(results):
    """CST space must be > 0."""
    assert results["space_bytes"] > 0


def test_space_bytes_reasonable(results, corpus):
    """CST space should be less than 10x the raw text size."""
    max_space = 10 * len(corpus)
    assert results["space_bytes"] < max_space, (
        f"space_bytes {results['space_bytes']} exceeds 10x text size ({max_space})"
    )


# ── JSON schema completeness ──


def test_all_required_keys_present(results):
    """All required JSON keys must be present."""
    required = {
        "num_internal_nodes",
        "num_leaves",
        "longest_repeat_length",
        "longest_repeat_string",
        "longest_repeat_frequency",
        "num_maximal_repeats",
        "num_supermaximal_repeats",
        "space_bytes",
        "pattern_counts",
    }
    missing = required - set(results.keys())
    assert not missing, f"Missing keys in results.json: {missing}"
