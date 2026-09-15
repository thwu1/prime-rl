"""
Tests for the rank-safe BM25 search engine with native C scoring library.

Verifies:
- C shared library (libscorer.so) existence, ELF validity, symbols, and correctness
- SQLite index schema and data consistency
- ctypes and sqlite3 usage in search_engine.py (no pickle)
- Rank-safe search results across diverse query types and edge cases
- CLI interface correctness (build + query)
- Anti-cheat: custom index object, independence from reference scorer
- Performance bounds

"""
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

sys.path.insert(0, "/app")

from reference import load_corpus, exhaustive_search
from search_engine import build_index, search


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ref_data():
    """Load corpus and build reference structures (once per module)."""
    index, doc_lengths, stats = load_corpus()
    return index, doc_lengths, stats


@pytest.fixture(scope="module")
def ms_index():
    """Build the agent's index via Python API (once per module)."""
    return build_index("/app/data/documents.jsonl", "/app/data/stats.json")


@pytest.fixture(scope="module")
def cli_index_path():
    """Build index via CLI and return the path (once per module)."""
    result = subprocess.run(
        ["python3", "/app/search_engine.py", "build"],
        capture_output=True, text=True, timeout=120, cwd="/app",
    )
    assert result.returncode == 0, f"CLI build failed: {result.stderr}"
    return "/app/index.db"


# ---------------------------------------------------------------------------
# C Library tests
# ---------------------------------------------------------------------------


def test_c_library_exists():
    """libscorer.so must exist at /app/libscorer.so."""
    assert os.path.isfile("/app/libscorer.so"), (
        "C shared library not found at /app/libscorer.so"
    )


def test_c_library_is_valid_elf():
    """libscorer.so must be a valid ELF shared library, not a dummy file."""
    with open("/app/libscorer.so", "rb") as f:
        magic = f.read(4)
    assert magic == b'\x7fELF', (
        "libscorer.so is not a valid ELF binary — must be compiled C code"
    )


def test_c_library_has_required_symbols():
    """libscorer.so must export bm25_score_block and advance_to_target."""
    lib = ctypes.CDLL("/app/libscorer.so")
    assert hasattr(lib, "bm25_score_block"), (
        "libscorer.so missing symbol: bm25_score_block"
    )
    assert hasattr(lib, "advance_to_target"), (
        "libscorer.so missing symbol: advance_to_target"
    )


def test_c_bm25_scoring_correctness():
    """C library bm25_score_block must match Python BM25 reference scores."""
    lib = ctypes.CDLL("/app/libscorer.so")
    lib.bm25_score_block.argtypes = [
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.c_int, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.POINTER(ctypes.c_double),
    ]
    lib.bm25_score_block.restype = ctypes.c_double

    from bm25 import bm25_term_score, idf as bm25_idf

    N = 20000
    df = 500
    avgdl = 175.0
    idf_val = bm25_idf(df, N)
    k1, b = 1.2, 0.75

    test_cases = [(1, 100), (5, 50), (2, 300), (10, 175), (1, 400), (3, 60)]
    tfs_list = [tc[0] for tc in test_cases]
    dls_list = [tc[1] for tc in test_cases]
    n = len(test_cases)

    c_tfs = (ctypes.c_int * n)(*tfs_list)
    c_dls = (ctypes.c_int * n)(*dls_list)
    c_scores = (ctypes.c_double * n)()
    c_max = lib.bm25_score_block(c_tfs, c_dls, n, idf_val, avgdl, k1, b, c_scores)

    py_scores = [bm25_term_score(tf, df, N, dl, avgdl) for tf, dl in test_cases]

    for i in range(n):
        assert abs(c_scores[i] - py_scores[i]) < 1e-10, (
            f"Score mismatch at index {i}: C={c_scores[i]:.15f}, "
            f"Python={py_scores[i]:.15f}"
        )
    assert abs(c_max - max(py_scores)) < 1e-10, (
        f"Max score mismatch: C={c_max:.15f}, Python={max(py_scores):.15f}"
    )


def test_c_bm25_different_idf():
    """C library scoring must work correctly across different IDF values."""
    lib = ctypes.CDLL("/app/libscorer.so")
    lib.bm25_score_block.argtypes = [
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
        ctypes.c_int, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.POINTER(ctypes.c_double),
    ]
    lib.bm25_score_block.restype = ctypes.c_double

    from bm25 import bm25_term_score, idf as bm25_idf

    N = 20000
    avgdl = 175.0
    k1, b = 1.2, 0.75

    # Test with rare term (high IDF)
    df_rare = 10
    idf_rare = bm25_idf(df_rare, N)
    c_tfs = (ctypes.c_int * 2)(2, 5)
    c_dls = (ctypes.c_int * 2)(100, 200)
    c_scores = (ctypes.c_double * 2)()
    lib.bm25_score_block(c_tfs, c_dls, 2, idf_rare, avgdl, k1, b, c_scores)

    for i, (tf, dl) in enumerate([(2, 100), (5, 200)]):
        expected = bm25_term_score(tf, df_rare, N, dl, avgdl)
        assert abs(c_scores[i] - expected) < 1e-10


def test_c_advance_to_target_correctness():
    """C library advance_to_target must correctly binary search sorted arrays."""
    lib = ctypes.CDLL("/app/libscorer.so")
    lib.advance_to_target.argtypes = [
        ctypes.POINTER(ctypes.c_int), ctypes.c_int,
        ctypes.c_int, ctypes.c_int,
    ]
    lib.advance_to_target.restype = ctypes.c_int

    doc_ids = [10, 20, 30, 40, 50]
    n = len(doc_ids)
    arr = (ctypes.c_int * n)(*doc_ids)

    # Exact matches
    assert lib.advance_to_target(arr, n, 0, 10) == 0
    assert lib.advance_to_target(arr, n, 0, 30) == 2
    assert lib.advance_to_target(arr, n, 0, 50) == 4

    # Between elements (should find next >=)
    assert lib.advance_to_target(arr, n, 0, 15) == 1   # 20 >= 15
    assert lib.advance_to_target(arr, n, 0, 25) == 2   # 30 >= 25
    assert lib.advance_to_target(arr, n, 0, 45) == 4   # 50 >= 45

    # Past end
    assert lib.advance_to_target(arr, n, 0, 51) == -1

    # Start offset
    assert lib.advance_to_target(arr, n, 3, 40) == 3
    assert lib.advance_to_target(arr, n, 3, 35) == 3   # 40 >= 35
    assert lib.advance_to_target(arr, n, 4, 50) == 4
    assert lib.advance_to_target(arr, n, 5, 10) == -1   # start past end

    # Single element array
    single = (ctypes.c_int * 1)(42)
    assert lib.advance_to_target(single, 1, 0, 42) == 0
    assert lib.advance_to_target(single, 1, 0, 43) == -1
    assert lib.advance_to_target(single, 1, 0, 1) == 0


# ---------------------------------------------------------------------------
# SQLite index tests
# ---------------------------------------------------------------------------


def test_sqlite_index_exists(cli_index_path):
    """CLI build must create a non-empty SQLite database."""
    assert os.path.isfile(cli_index_path), (
        f"Index database not found at {cli_index_path}"
    )
    assert os.path.getsize(cli_index_path) > 0, "Index database is empty"


def test_sqlite_has_required_tables(cli_index_path):
    """SQLite index must contain corpus_stats, terms, blocks, doc_lengths."""
    conn = sqlite3.connect(cli_index_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()

    for table in ["corpus_stats", "terms", "blocks", "doc_lengths"]:
        assert table in tables, f"Missing required table: {table}"


def test_sqlite_data_consistency(cli_index_path):
    """SQLite index must contain consistent data matching the corpus."""
    conn = sqlite3.connect(cli_index_path)
    doc_count = conn.execute("SELECT COUNT(*) FROM doc_lengths").fetchone()[0]
    term_count = conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
    block_count = conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
    conn.close()

    assert doc_count == 20000, (
        f"Expected 20000 documents in doc_lengths, got {doc_count}"
    )
    assert term_count > 100, (
        f"Expected >100 terms in index, got {term_count}"
    )
    assert block_count > term_count, (
        f"Expected more blocks ({block_count}) than terms ({term_count})"
    )


def test_sqlite_roundtrip_rank_safety(ref_data, cli_index_path):
    """Index loaded from SQLite must produce rank-safe results."""
    from search_engine import load_index

    index, doc_lengths, stats = ref_data
    loaded = load_index(cli_index_path)

    query = ["t0", "t1", "t50", "t500", "t5000"]
    k = 10
    ref_results = exhaustive_search(index, doc_lengths, stats, query, k)
    loaded_results = search(loaded, query, k)

    assert len(loaded_results) == len(ref_results)
    for i, ((ri, rs), (li, ls)) in enumerate(
        zip(ref_results, loaded_results)
    ):
        assert ri == li, f"Position {i}: doc_id mismatch after SQLite roundtrip"
        assert abs(rs - ls) < 1e-6, f"Position {i}: score mismatch after roundtrip"


# ---------------------------------------------------------------------------
# Source code inspection (anti-cheat)
# ---------------------------------------------------------------------------


def test_engine_uses_ctypes():
    """search_engine.py must import ctypes and reference libscorer."""
    with open("/app/search_engine.py") as f:
        src = f.read()
    assert "ctypes" in src, (
        "search_engine.py must use ctypes to load the C library"
    )
    assert "libscorer" in src, (
        "search_engine.py must load libscorer.so via ctypes"
    )


def test_engine_uses_sqlite3():
    """search_engine.py must use sqlite3 for index persistence."""
    with open("/app/search_engine.py") as f:
        src = f.read()
    assert "sqlite3" in src, (
        "search_engine.py must use sqlite3 for index persistence"
    )


def test_engine_no_pickle():
    """Index persistence must use SQLite, not pickle."""
    with open("/app/search_engine.py") as f:
        src = f.read()
    # Allow "pickle" in comments but not as an import
    lines = [l.strip() for l in src.split('\n')
             if l.strip() and not l.strip().startswith('#')]
    code = '\n'.join(lines)
    assert "import pickle" not in code, (
        "Must use SQLite for persistence, not pickle"
    )


# ---------------------------------------------------------------------------
# Rank-safety parametrized tests (Python API)
# ---------------------------------------------------------------------------


QUERIES = [
    (["t4000"], 10),
    (["t0", "t1"], 10),
    (["t50", "t500", "t5000"], 10),
    (["t0", "t1", "t2", "t3"], 10),
    (["t100", "t200", "t300", "t400", "t500", "t600", "t700"], 10),
    (["t0", "t1", "t2", "t10", "t50", "t100",
      "t200", "t500", "t1000", "t2000", "t3000",
      "t5000", "t7000"], 10),
    (["t99", "t500"], 20),
    (["t0", "t1", "t2", "t3", "t4", "t5"], 10),
    (["t3000", "t4000", "t5000", "t6000", "t7000"], 10),
    (["t500"], 5),
    (["t0", "t7999"], 10),
    (["t100", "t200", "t300", "t400", "t500"], 100),
    (["t0"], 10),
    (["t0", "t1", "t2", "t3", "t4", "t5",
      "t6", "t7", "t8", "t9"], 10),
    (["t0", "t1", "t2", "t3", "t4", "t5",
      "t6", "t7", "t8", "t9", "t10", "t11",
      "t12", "t13", "t14"], 5),
]


@pytest.mark.parametrize("query_terms,k", QUERIES, ids=[
    "single_rare", "two_common", "mixed_freq", "four_common",
    "seven_medium", "thirteen_mixed", "two_med_k20", "six_common",
    "five_rare", "single_med_k5", "common_plus_rare", "five_med_k100",
    "single_most_common", "ten_common", "fifteen_terms_k5",
])
def test_rank_safety(ref_data, ms_index, query_terms, k):
    """search() must return identical results to exhaustive search."""
    index, doc_lengths, stats = ref_data

    ref_results = exhaustive_search(index, doc_lengths, stats, query_terms, k)
    ms_results = search(ms_index, query_terms, k)

    assert len(ms_results) == len(ref_results), (
        f"Result count mismatch for query {query_terms}: "
        f"expected {len(ref_results)}, got {len(ms_results)}"
    )

    for i, ((ref_id, ref_score), (ms_id, ms_score)) in enumerate(
        zip(ref_results, ms_results)
    ):
        assert ref_id == ms_id, (
            f"Position {i}: doc_id mismatch for query {query_terms}: "
            f"expected {ref_id}, got {ms_id}"
        )
        assert abs(ref_score - ms_score) < 1e-6, (
            f"Position {i}: score mismatch for query {query_terms}: "
            f"expected {ref_score:.10f}, got {ms_score:.10f}"
        )


# ---------------------------------------------------------------------------
# Edge case tests (Python API)
# ---------------------------------------------------------------------------


def test_empty_query(ms_index):
    """Empty query returns empty results."""
    result = search(ms_index, [], 10)
    assert result == []


def test_nonexistent_terms(ms_index):
    """Query with non-existent terms returns empty results."""
    result = search(ms_index, ["nonexistent_xyz", "also_missing_abc"], 10)
    assert result == []


def test_k_one(ref_data, ms_index):
    """k=1 must return the single best result."""
    index, doc_lengths, stats = ref_data
    query = ["t50", "t500", "t5000"]
    ref = exhaustive_search(index, doc_lengths, stats, query, 1)
    ms = search(ms_index, query, 1)

    assert len(ms) == 1
    assert ms[0][0] == ref[0][0]
    assert abs(ms[0][1] - ref[0][1]) < 1e-6


def test_large_k(ref_data, ms_index):
    """k larger than matching docs returns all matches correctly."""
    index, doc_lengths, stats = ref_data
    query = ["t7500"]  # very rare term
    ref = exhaustive_search(index, doc_lengths, stats, query, 10000)
    ms = search(ms_index, query, 10000)

    assert len(ms) == len(ref)
    for (ref_id, ref_score), (ms_id, ms_score) in zip(ref, ms):
        assert ref_id == ms_id
        assert abs(ref_score - ms_score) < 1e-6


def test_score_ordering(ms_index):
    """Results must be sorted by descending score, ascending doc_id for ties."""
    query = ["t0", "t1", "t2", "t100", "t500"]
    results = search(ms_index, query, 50)

    for i in range(len(results) - 1):
        id_a, score_a = results[i]
        id_b, score_b = results[i + 1]
        assert score_a >= score_b - 1e-9, (
            f"Position {i}: scores not in descending order: "
            f"{score_a} then {score_b}"
        )
        if abs(score_a - score_b) < 1e-9:
            assert id_a < id_b, (
                f"Position {i}: tied scores but doc_ids not ascending: "
                f"{id_a} then {id_b}"
            )


def test_duplicate_query_terms(ref_data, ms_index):
    """Duplicate query terms should be treated as one occurrence."""
    index, doc_lengths, stats = ref_data
    query = ["t100", "t100", "t200"]
    query_dedup = ["t100", "t200"]

    ref = exhaustive_search(index, doc_lengths, stats, query_dedup, 10)
    ms = search(ms_index, query, 10)

    assert len(ms) == len(ref)
    for (ref_id, ref_score), (ms_id, ms_score) in zip(ref, ms):
        assert ref_id == ms_id
        assert abs(ref_score - ms_score) < 1e-6


# ---------------------------------------------------------------------------
# Structural and anti-cheat tests
# ---------------------------------------------------------------------------


def test_index_is_custom_object(ms_index):
    """build_index must return a custom index object, not a raw collection."""
    assert not isinstance(ms_index, (tuple, list, dict, set)), (
        "build_index must return a custom index object, "
        "not a raw tuple/list/dict/set"
    )


def test_search_independent_of_reference(ms_index):
    """search() must not delegate to reference.exhaustive_search at runtime."""
    import reference as ref

    original = ref.exhaustive_search
    call_log = []

    def interceptor(*args, **kwargs):
        call_log.append(True)
        return original(*args, **kwargs)

    ref.exhaustive_search = interceptor
    try:
        search(ms_index, ["t0", "t1", "t50", "t200"], 10)
    finally:
        ref.exhaustive_search = original

    assert len(call_log) == 0, (
        "search() must not call reference.exhaustive_search — "
        "implement search independently"
    )


def test_search_performance_long_query(ref_data, ms_index):
    """For 15-term queries, must not be drastically slower than exhaustive."""
    index, doc_lengths, stats = ref_data
    query = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
             "t8", "t9", "t10", "t11", "t12", "t13", "t14"]
    k = 10
    iters = 10

    start = time.perf_counter()
    for _ in range(iters):
        exhaustive_search(index, doc_lengths, stats, query, k)
    t_ex = (time.perf_counter() - start) / iters

    start = time.perf_counter()
    for _ in range(iters):
        search(ms_index, query, k)
    t_ms = (time.perf_counter() - start) / iters

    assert t_ms < t_ex * 5.0, (
        f"search() is too slow ({t_ms:.4f}s) compared to exhaustive "
        f"({t_ex:.4f}s). Must be within 5x."
    )


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_build_creates_index(cli_index_path):
    """CLI build subcommand must create a non-empty index database on disk."""
    assert os.path.isfile(cli_index_path), (
        f"Index file not found at {cli_index_path}"
    )
    assert os.path.getsize(cli_index_path) > 0, "Index file is empty"


def test_cli_query_rank_safety(ref_data, cli_index_path):
    """CLI query must return results matching exhaustive search."""
    index, doc_lengths, stats = ref_data
    query_terms = ["t50", "t500", "t5000"]
    k = 10

    ref_results = exhaustive_search(index, doc_lengths, stats, query_terms, k)

    result = subprocess.run(
        ["python3", "/app/search_engine.py", "query",
         "--index", cli_index_path, "-k", str(k)] + query_terms,
        capture_output=True, text=True, timeout=30, cwd="/app",
    )
    assert result.returncode == 0, f"CLI query failed: {result.stderr}"

    cli_results = json.loads(result.stdout.strip())
    assert len(cli_results) == len(ref_results), (
        f"CLI result count mismatch: expected {len(ref_results)}, "
        f"got {len(cli_results)}"
    )

    for i, ((ref_id, ref_score), cli_pair) in enumerate(
        zip(ref_results, cli_results)
    ):
        assert cli_pair[0] == ref_id, (
            f"CLI position {i}: doc_id mismatch: "
            f"expected {ref_id}, got {cli_pair[0]}"
        )
        assert abs(cli_pair[1] - ref_score) < 1e-6, (
            f"CLI position {i}: score mismatch: "
            f"expected {ref_score:.10f}, got {cli_pair[1]:.10f}"
        )


def test_cli_query_no_terms(cli_index_path):
    """CLI query with no terms returns empty JSON array."""
    result = subprocess.run(
        ["python3", "/app/search_engine.py", "query",
         "--index", cli_index_path, "-k", "10"],
        capture_output=True, text=True, timeout=30, cwd="/app",
    )
    assert result.returncode == 0, f"CLI query (no terms) failed: {result.stderr}"
    assert json.loads(result.stdout.strip()) == []


def test_cli_query_json_format(cli_index_path):
    """CLI output must be valid JSON array of [doc_id, score] pairs."""
    result = subprocess.run(
        ["python3", "/app/search_engine.py", "query",
         "--index", cli_index_path, "-k", "5", "t0", "t1"],
        capture_output=True, text=True, timeout=30, cwd="/app",
    )
    assert result.returncode == 0, f"CLI query failed: {result.stderr}"

    data = json.loads(result.stdout.strip())
    assert isinstance(data, list), "CLI output must be a JSON array"
    assert len(data) > 0, "Expected non-empty results for t0+t1"
    for item in data:
        assert isinstance(item, list), "Each result must be a [doc_id, score] array"
        assert len(item) == 2, "Each result must have exactly 2 elements"
        assert isinstance(item[0], int), "doc_id must be an integer"
        assert isinstance(item[1], (int, float)), "score must be a number"


def test_cli_query_multiterm(ref_data, cli_index_path):
    """CLI query with many terms must match reference."""
    index, doc_lengths, stats = ref_data
    query_terms = ["t0", "t1", "t2", "t3", "t4"]
    k = 5

    ref_results = exhaustive_search(index, doc_lengths, stats, query_terms, k)

    result = subprocess.run(
        ["python3", "/app/search_engine.py", "query",
         "--index", cli_index_path, "-k", str(k)] + query_terms,
        capture_output=True, text=True, timeout=30, cwd="/app",
    )
    assert result.returncode == 0, f"CLI query failed: {result.stderr}"

    cli_results = json.loads(result.stdout.strip())
    assert len(cli_results) == len(ref_results)
    for (ref_id, ref_score), cli_pair in zip(ref_results, cli_results):
        assert cli_pair[0] == ref_id
        assert abs(cli_pair[1] - ref_score) < 1e-6
