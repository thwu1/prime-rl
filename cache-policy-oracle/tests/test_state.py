"""Tests for the hybrid C/Python cache replacement policy evaluation framework.

Verifies native engine compilation, cross-engine validation, policy correctness,
SHiP implementation, and comparative ranking analysis.
"""

import json
import os
import ctypes
import pytest

RESULTS_PATH = "/app/results.json"
RANKING_PATH = "/app/policy_ranking.json"
TRACE_DIR = "/app/traces"
NATIVE_LIB = "/app/native/libcachesim.so"
POLICIES = ["lru", "srrip", "drrip", "opt", "ship"]
PRACTICAL_POLICIES = ["lru", "srrip", "drrip", "ship"]
TRACE_NAMES = [
    "trace_temporal", "trace_scan", "trace_mixed",
    "trace_thrash", "trace_micro",
]


@pytest.fixture
def results():
    assert os.path.isfile(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "policies" in data
    return data


@pytest.fixture
def ranking():
    assert os.path.isfile(RANKING_PATH), f"{RANKING_PATH} does not exist"
    with open(RANKING_PATH) as f:
        data = json.load(f)
    return data


def _load_native():
    lib = ctypes.CDLL(NATIVE_LIB)
    lib.csim_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.csim_create.restype = ctypes.c_void_p
    lib.csim_access.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.csim_access.restype = ctypes.c_int
    lib.csim_destroy.argtypes = [ctypes.c_void_p]
    lib.csim_destroy.restype = None
    return lib


def _run_native_lru(lib, trace_path, num_sets=256, num_ways=16, block_size=64):
    cache = lib.csim_create(num_sets, num_ways, block_size)
    hits = 0
    misses = 0
    with open(trace_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            addr = int(parts[1], 16)
            result = lib.csim_access(cache, ctypes.c_uint64(addr))
            if result == 1:
                hits += 1
            else:
                misses += 1
    lib.csim_destroy(cache)
    return hits, misses


# ===== Native engine tests =====

class TestNativeEngine:
    def test_shared_library_exists(self):
        assert os.path.isfile(NATIVE_LIB), \
            f"Native library not found at {NATIVE_LIB}"

    def test_library_loadable_and_exports(self):
        lib = ctypes.CDLL(NATIVE_LIB)
        assert hasattr(lib, 'csim_create')
        assert hasattr(lib, 'csim_access')
        assert hasattr(lib, 'csim_destroy')

    def test_native_lru_micro_trace(self):
        """C LRU engine must match Python LRU: 32 misses, 0 hits on micro."""
        lib = _load_native()
        trace_path = os.path.join(TRACE_DIR, "trace_micro.txt")
        hits, misses = _run_native_lru(lib, trace_path)
        assert misses == 32, f"C LRU micro misses={misses}, expected 32"
        assert hits == 0, f"C LRU micro hits={hits}, expected 0"

    def test_native_lru_temporal_low_miss_rate(self):
        """C LRU on temporal trace must have very low miss rate."""
        lib = _load_native()
        trace_path = os.path.join(TRACE_DIR, "trace_temporal.txt")
        hits, misses = _run_native_lru(lib, trace_path)
        total = hits + misses
        miss_rate = misses / total if total > 0 else 1.0
        assert miss_rate < 0.01, \
            f"C LRU temporal miss_rate={miss_rate:.6f}, expected < 0.01"

    def test_native_cross_validates_python_lru(self, results):
        """C LRU results must exactly match Python LRU on all traces."""
        lib = _load_native()
        for tname in TRACE_NAMES:
            trace_path = os.path.join(TRACE_DIR, tname + ".txt")
            c_hits, c_misses = _run_native_lru(lib, trace_path)
            py_data = results["policies"]["lru"]["per_trace"][tname]
            assert c_hits == py_data["hits"], \
                f"{tname}: C hits={c_hits} != Python hits={py_data['hits']}"
            assert c_misses == py_data["misses"], \
                f"{tname}: C misses={c_misses} != Python misses={py_data['misses']}"


# ===== Schema and completeness =====

class TestSchema:
    def test_all_policies_present(self, results):
        for p in POLICIES:
            assert p in results["policies"], f"Missing policy: {p}"

    def test_all_traces_present(self, results):
        for p in POLICIES:
            per_trace = results["policies"][p]["per_trace"]
            for t in TRACE_NAMES:
                assert t in per_trace, \
                    f"Policy '{p}' missing trace '{t}'"

    def test_required_fields(self, results):
        for p in POLICIES:
            pdata = results["policies"][p]
            assert "storage_bytes" in pdata
            assert "geomean_miss_rate_reduction" in pdata
            for t in TRACE_NAMES:
                td = pdata["per_trace"][t]
                for field in ["accesses", "hits", "misses",
                              "miss_rate", "hit_rate"]:
                    assert field in td, \
                        f"Policy '{p}', trace '{t}' missing '{field}'"


# ===== Arithmetic invariants =====

class TestInvariants:
    def test_hits_plus_misses_equals_accesses(self, results):
        for p in POLICIES:
            for t in TRACE_NAMES:
                td = results["policies"][p]["per_trace"][t]
                assert td["hits"] + td["misses"] == td["accesses"], \
                    f"{p}/{t}: {td['hits']}+{td['misses']}!={td['accesses']}"

    def test_rates_valid_and_sum_to_one(self, results):
        for p in POLICIES:
            for t in TRACE_NAMES:
                td = results["policies"][p]["per_trace"][t]
                assert 0.0 <= td["miss_rate"] <= 1.0
                assert 0.0 <= td["hit_rate"] <= 1.0
                assert abs(td["miss_rate"] + td["hit_rate"] - 1.0) < 1e-6

    def test_accesses_match_trace_lines(self, results):
        for t in TRACE_NAMES:
            trace_path = os.path.join(TRACE_DIR, t + ".txt")
            line_count = sum(
                1 for line in open(trace_path)
                if line.strip() and not line.startswith('#')
            )
            for p in POLICIES:
                td = results["policies"][p]["per_trace"][t]
                assert td["accesses"] == line_count, \
                    f"{p}/{t}: accesses={td['accesses']} != lines={line_count}"


# ===== OPT optimality =====

class TestOptimality:
    def test_opt_leq_all_policies(self, results):
        """OPT must have miss_rate <= every other policy on every trace."""
        for p in POLICIES:
            if p == "opt":
                continue
            for t in TRACE_NAMES:
                opt_mr = results["policies"]["opt"]["per_trace"][t]["miss_rate"]
                pol_mr = results["policies"][p]["per_trace"][t]["miss_rate"]
                assert opt_mr <= pol_mr + 1e-9, \
                    f"OPT({opt_mr}) > {p}({pol_mr}) on {t}"


# ===== Micro-trace exact results =====

class TestMicroTrace:
    def test_micro_accesses(self, results):
        for p in POLICIES:
            td = results["policies"][p]["per_trace"]["trace_micro"]
            assert td["accesses"] == 32

    def test_micro_opt_misses(self, results):
        """OPT on micro: 20 misses (evicts blocks 12-15 with no future use)."""
        assert results["policies"]["opt"]["per_trace"]["trace_micro"]["misses"] == 20

    def test_micro_lru_misses(self, results):
        """LRU on micro: 32 misses (all accesses miss due to thrashing)."""
        assert results["policies"]["lru"]["per_trace"]["trace_micro"]["misses"] == 32

    def test_micro_ship_misses(self, results):
        """SHiP on micro: 21 misses (BRRIP-like insertion protects ways 1-15)."""
        assert results["policies"]["ship"]["per_trace"]["trace_micro"]["misses"] == 21

    def test_micro_ship_better_than_lru(self, results):
        ship_m = results["policies"]["ship"]["per_trace"]["trace_micro"]["misses"]
        lru_m = results["policies"]["lru"]["per_trace"]["trace_micro"]["misses"]
        assert ship_m < lru_m


# ===== Storage budgets =====

class TestStorage:
    def test_lru_storage(self, results):
        """LRU: 256*16*ceil(log2(16))=256*16*4=16384 bits = 2048 bytes."""
        assert results["policies"]["lru"]["storage_bytes"] == 2048

    def test_srrip_storage(self, results):
        """SRRIP: 256*16*3=12288 bits = 1536 bytes."""
        assert results["policies"]["srrip"]["storage_bytes"] == 1536

    def test_opt_storage(self, results):
        """OPT: unbounded offline oracle, reports -1."""
        assert results["policies"]["opt"]["storage_bytes"] == -1

    def test_drrip_storage(self, results):
        """DRRIP storage exceeds SRRIP (PSEL counter) and fits 32KB."""
        drrip_s = results["policies"]["drrip"]["storage_bytes"]
        srrip_s = results["policies"]["srrip"]["storage_bytes"]
        assert drrip_s > srrip_s, \
            f"DRRIP({drrip_s}) must exceed SRRIP({srrip_s})"
        assert drrip_s < 32768

    def test_ship_storage(self, results):
        """SHiP: (256*16*(3+14) + 2^14*3 + 7)//8 = 14848 bytes."""
        assert results["policies"]["ship"]["storage_bytes"] == 14848

    def test_all_practical_under_budget(self, results):
        for p in PRACTICAL_POLICIES:
            s = results["policies"][p]["storage_bytes"]
            assert 0 < s < 32768, f"{p} storage={s} out of (0, 32768)"


# ===== Geomean constraints =====

class TestGeomean:
    def test_lru_geomean_is_one(self, results):
        g = results["policies"]["lru"]["geomean_miss_rate_reduction"]
        assert abs(g - 1.0) < 1e-6

    def test_opt_geomean_geq_one(self, results):
        g = results["policies"]["opt"]["geomean_miss_rate_reduction"]
        assert g >= 1.0 - 1e-6

    def test_all_geomeans_positive(self, results):
        for p in POLICIES:
            g = results["policies"][p]["geomean_miss_rate_reduction"]
            assert g > 0, f"{p} geomean={g}"


# ===== Policy performance relationships =====

class TestPerformance:
    def test_ship_outperforms_srrip_on_mixed(self, results):
        """SHiP uses PC to distinguish hot (0x2000) from scan (0x3000)."""
        ship_mr = results["policies"]["ship"]["per_trace"]["trace_mixed"]["miss_rate"]
        srrip_mr = results["policies"]["srrip"]["per_trace"]["trace_mixed"]["miss_rate"]
        assert ship_mr < srrip_mr, \
            f"SHiP({ship_mr}) should outperform SRRIP({srrip_mr}) on mixed"

    def test_srrip_outperforms_lru_on_mixed(self, results):
        srrip_mr = results["policies"]["srrip"]["per_trace"]["trace_mixed"]["miss_rate"]
        lru_mr = results["policies"]["lru"]["per_trace"]["trace_mixed"]["miss_rate"]
        assert srrip_mr < lru_mr

    def test_temporal_low_miss_rate(self, results):
        for p in POLICIES:
            mr = results["policies"][p]["per_trace"]["trace_temporal"]["miss_rate"]
            assert mr < 0.01, f"{p} temporal miss_rate={mr}"

    def test_scan_high_miss_rate_for_lru(self, results):
        mr = results["policies"]["lru"]["per_trace"]["trace_scan"]["miss_rate"]
        assert mr > 0.7

    def test_opt_improves_on_scan(self, results):
        opt_mr = results["policies"]["opt"]["per_trace"]["trace_scan"]["miss_rate"]
        lru_mr = results["policies"]["lru"]["per_trace"]["trace_scan"]["miss_rate"]
        assert opt_mr < lru_mr - 0.01


# ===== Policy ranking analysis =====

class TestRanking:
    def test_ranking_structure(self, ranking):
        assert "per_trace_best" in ranking
        assert "overall_ranking" in ranking
        assert "champion" in ranking

    def test_ranking_traces_complete(self, ranking):
        for t in TRACE_NAMES:
            assert t in ranking["per_trace_best"], f"Missing trace {t}"

    def test_ranking_policies_valid(self, ranking):
        for t, p in ranking["per_trace_best"].items():
            assert p in PRACTICAL_POLICIES, \
                f"Invalid policy '{p}' for trace '{t}'"
        for p in ranking["overall_ranking"]:
            assert p in PRACTICAL_POLICIES
        assert ranking["champion"] in PRACTICAL_POLICIES

    def test_ranking_all_practical_policies(self, ranking):
        assert set(ranking["overall_ranking"]) == set(PRACTICAL_POLICIES)

    def test_per_trace_best_consistent(self, results, ranking):
        """per_trace_best must match the lowest-miss-rate practical policy."""
        for t in TRACE_NAMES:
            best_p = ranking["per_trace_best"][t]
            best_mr = results["policies"][best_p]["per_trace"][t]["miss_rate"]
            for p in PRACTICAL_POLICIES:
                other_mr = results["policies"][p]["per_trace"][t]["miss_rate"]
                assert best_mr <= other_mr + 1e-9, \
                    f"{t}: ranked {best_p}({best_mr}) but {p}({other_mr}) is better"

    def test_overall_ranking_sorted(self, results, ranking):
        """overall_ranking sorted by descending geomean_miss_rate_reduction."""
        geomeans = [
            results["policies"][p]["geomean_miss_rate_reduction"]
            for p in ranking["overall_ranking"]
        ]
        for i in range(len(geomeans) - 1):
            assert geomeans[i] >= geomeans[i + 1] - 1e-9, \
                f"Not sorted: {ranking['overall_ranking'][i]}({geomeans[i]}) "\
                f"< {ranking['overall_ranking'][i+1]}({geomeans[i+1]})"

    def test_champion_is_first(self, ranking):
        assert ranking["champion"] == ranking["overall_ranking"][0]
