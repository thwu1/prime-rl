"""Verification tests for the COCO benchmarking pipeline output."""

import json
import math
import os

import pytest

# ---------------------------------------------------------------------------
# Load benchmark data directly from TSV (independent of the pipeline)
# ---------------------------------------------------------------------------
DATA_DIR = "/app/raw_data"

with open(os.path.join(DATA_DIR, "metadata.json")) as _f:
    META = json.load(_f)

ALGORITHMS = META["algorithms"]
FUNCTIONS = META["functions"]
DIMENSIONS = META["dimensions"]
TARGETS = META["targets"]
FUNCTION_GROUPS = META["function_groups"]
BUDGETS = [100, 500, 1000, 5000, 10000, 50000, 100000, 500000]
PERF_THRESHOLDS = [1.0, 1.5, 2.0, 5.0, 10.0]

# Parse TSV files to build run data (completely independent of pipeline)
ALL_RUNS: dict[str, list[dict]] = {}
for _algo in ALGORITHMS:
    _runs_by_key: dict[tuple, dict] = {}
    with open(os.path.join(DATA_DIR, f"{_algo}.tsv")) as _f:
        for _line in _f:
            if _line.startswith("#") or not _line.strip():
                continue
            _parts = _line.strip().split("\t")
            _func_id = int(_parts[0])
            _dim = int(_parts[1])
            _inst = int(_parts[2])
            _budget = int(float(_parts[3]))
            _target = _parts[4]
            _evals = int(_parts[5])

            _key = (_func_id, _dim, _inst)
            if _key not in _runs_by_key:
                _runs_by_key[_key] = {
                    "function_id": _func_id,
                    "dimension": _dim,
                    "instance": _inst,
                    "budget": _budget,
                    "targets_reached": {},
                }
            _runs_by_key[_key]["targets_reached"][_target] = _evals
    ALL_RUNS[_algo] = list(_runs_by_key.values())


def _get_runs(algo: str, func: int, dim: int) -> list[dict]:
    return [r for r in ALL_RUNS[algo]
            if r["function_id"] == func and r["dimension"] == dim]


# ---------------------------------------------------------------------------
# Reference implementations (independent ground truth)
# ---------------------------------------------------------------------------
def _ref_ert(algo: str, func: int, dim: int, target: str):
    """Compute reference ERT value using correct methodology."""
    runs = _get_runs(algo, func, dim)
    total_cost = 0
    n_success = 0
    for run in runs:
        if target in run["targets_reached"]:
            total_cost += run["targets_reached"][target]
            n_success += 1
        else:
            total_cost += run["budget"]
    if n_success == 0:
        return None
    return total_cost / n_success


def _ref_ecdf(algo: str, dim: int, budget_threshold: int) -> float:
    """Compute reference ECDF value."""
    total = 0
    solved = 0
    for func in FUNCTIONS:
        for run in _get_runs(algo, func, dim):
            for target in TARGETS:
                total += 1
                if (target in run["targets_reached"]
                        and run["targets_reached"][target] <= budget_threshold):
                    solved += 1
    return solved / total if total > 0 else 0.0


def _ref_rankings(group_name: str) -> list[str]:
    """Compute reference algorithm ranking for a function group."""
    group_funcs = FUNCTION_GROUPS[group_name]
    algo_scores = {}
    for algo in ALGORITHMS:
        log_erts = []
        for func in group_funcs:
            for dim in DIMENSIONS:
                ert = _ref_ert(algo, func, dim, "0.01")
                if ert is None:
                    log_erts.append(math.log(2 * 10000 * dim))
                else:
                    log_erts.append(math.log(ert))
        algo_scores[algo] = math.exp(sum(log_erts) / len(log_erts))
    return sorted(ALGORITHMS, key=lambda a: (algo_scores[a], a))


def _ref_scaling(algo: str, func: int):
    """Compute reference scaling exponent via log-log OLS regression."""
    log_dims = []
    log_erts = []
    for dim in DIMENSIONS:
        ert = _ref_ert(algo, func, dim, "1e-08")
        if ert is not None:
            log_dims.append(math.log(dim))
            log_erts.append(math.log(ert))
    if len(log_dims) < 2:
        return None
    n = len(log_dims)
    x_mean = sum(log_dims) / n
    y_mean = sum(log_erts) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(log_dims, log_erts))
    den = sum((x - x_mean) ** 2 for x in log_dims)
    if den == 0:
        return None
    return num / den


def _ref_vbs_ert(func: int, dim: int, target: str):
    """Virtual Best Solver: minimum finite ERT across all algorithms."""
    best = None
    for algo in ALGORITHMS:
        ert = _ref_ert(algo, func, dim, target)
        if ert is not None:
            if best is None or ert < best:
                best = ert
    return best


def _ref_algorithm_selection(func: int, dim: int, target: str):
    """Which algorithm achieves VBS ERT. Alphabetical tie-breaking."""
    best_ert = None
    best_algo = None
    for algo in sorted(ALGORITHMS):
        ert = _ref_ert(algo, func, dim, target)
        if ert is not None:
            if best_ert is None or ert < best_ert:
                best_ert = ert
                best_algo = algo
    return best_algo


def _ref_performance_profile(algo: str, tau: float) -> float:
    """Fraction of solvable scenarios where algo ERT <= tau * VBS ERT."""
    total = 0
    within = 0
    for func in FUNCTIONS:
        for dim in DIMENSIONS:
            for target in TARGETS:
                vbs = _ref_vbs_ert(func, dim, target)
                if vbs is not None:
                    total += 1
                    ert = _ref_ert(algo, func, dim, target)
                    if ert is not None and ert <= tau * vbs:
                        within += 1
    return within / total if total > 0 else 0.0


# ---------------------------------------------------------------------------
# Load agent results
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------
class TestStructure:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_top_level_keys(self, results):
        for key in ["ert", "ecdf", "rankings", "scaling_exponents",
                     "vbs_ert", "algorithm_selection", "performance_profile"]:
            assert key in results, f"Missing top-level key: {key}"

    def test_ert_keys_complete(self, results):
        for algo in ALGORITHMS:
            for func in FUNCTIONS:
                for dim in DIMENSIONS:
                    for target in TARGETS:
                        key = f"{algo}_f{func}_d{dim}_t{target}"
                        assert key in results["ert"], f"Missing ERT key: {key}"

    def test_ecdf_keys_complete(self, results):
        for algo in ALGORITHMS:
            for dim in DIMENSIONS:
                for budget in BUDGETS:
                    key = f"{algo}_d{dim}_b{budget}"
                    assert key in results["ecdf"], f"Missing ECDF key: {key}"

    def test_ranking_keys_complete(self, results):
        for group in FUNCTION_GROUPS:
            assert group in results["rankings"], f"Missing ranking: {group}"

    def test_scaling_keys_complete(self, results):
        for algo in ALGORITHMS:
            for func in FUNCTIONS:
                key = f"{algo}_f{func}"
                assert key in results["scaling_exponents"], \
                    f"Missing scaling key: {key}"

    def test_vbs_keys_complete(self, results):
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    assert key in results["vbs_ert"], \
                        f"Missing VBS key: {key}"

    def test_selection_keys_complete(self, results):
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    assert key in results["algorithm_selection"], \
                        f"Missing selection key: {key}"

    def test_profile_keys_complete(self, results):
        for algo in ALGORITHMS:
            for tau in PERF_THRESHOLDS:
                key = f"{algo}_tau{tau}"
                assert key in results["performance_profile"], \
                    f"Missing profile key: {key}"


# ---------------------------------------------------------------------------
# ERT tests
# ---------------------------------------------------------------------------
class TestERT:
    def test_ert_all_values(self, results):
        """Verify every ERT value against independent computation."""
        mismatches = []
        for algo in ALGORITHMS:
            for func in FUNCTIONS:
                for dim in DIMENSIONS:
                    for target in TARGETS:
                        key = f"{algo}_f{func}_d{dim}_t{target}"
                        expected = _ref_ert(algo, func, dim, target)
                        actual = results["ert"].get(key)
                        if expected is None:
                            if actual is not None:
                                mismatches.append(
                                    f"{key}: expected null, got {actual}")
                        else:
                            if actual is None:
                                mismatches.append(
                                    f"{key}: expected {expected}, got null")
                            elif abs(actual - expected) > 1e-6 * abs(expected) + 1e-10:
                                mismatches.append(
                                    f"{key}: expected {expected}, got {actual}")
        assert not mismatches, (
            f"{len(mismatches)} ERT mismatches:\n"
            + "\n".join(mismatches[:20]))

    def test_ert_easy_case_all_finite(self, results):
        """CMAES on f1 (Sphere) should reach all targets at all dimensions."""
        for dim in DIMENSIONS:
            for target in TARGETS:
                key = f"CMAES_f1_d{dim}_t{target}"
                assert results["ert"][key] is not None, \
                    f"{key} should be finite (Sphere is easy for CMA-ES)"

    def test_ert_hard_case_all_null(self, results):
        """NelderMead on f15 at dim=40, hard targets should be null."""
        for target in ["0.0001", "1e-08"]:
            key = f"NelderMead_f15_d40_t{target}"
            assert results["ert"][key] is None, \
                f"{key} should be null (NM fails on Rastrigin in high dim)"

    def test_ert_partial_success(self, results):
        """CMAES on f21 dim=40 at 1e-08: partial success (1 of 5)."""
        key = "CMAES_f21_d40_t1e-08"
        val = results["ert"][key]
        assert val is not None, f"{key} should be finite (1 run succeeds)"
        expected = _ref_ert("CMAES", 21, 40, "1e-08")
        assert abs(val - expected) < 1.0, \
            f"{key}: expected ~{expected}, got {val}"
        # ERT >> budget because 4 runs contribute full budget
        assert val > 400000, \
            f"{key} should be > budget (400000), got {val}"


# ---------------------------------------------------------------------------
# ECDF tests
# ---------------------------------------------------------------------------
class TestECDF:
    def test_ecdf_all_values(self, results):
        """Verify every ECDF value against independent computation."""
        mismatches = []
        for algo in ALGORITHMS:
            for dim in DIMENSIONS:
                for budget in BUDGETS:
                    key = f"{algo}_d{dim}_b{budget}"
                    expected = _ref_ecdf(algo, dim, budget)
                    actual = results["ecdf"].get(key)
                    if actual is None:
                        mismatches.append(f"{key}: missing")
                    elif abs(actual - expected) > 1e-10:
                        mismatches.append(
                            f"{key}: expected {expected}, got {actual}")
        assert not mismatches, (
            f"{len(mismatches)} ECDF mismatches:\n"
            + "\n".join(mismatches[:20]))

    def test_ecdf_monotonic(self, results):
        """ECDF must be non-decreasing with budget."""
        for algo in ALGORITHMS:
            for dim in DIMENSIONS:
                prev = -1.0
                for budget in BUDGETS:
                    key = f"{algo}_d{dim}_b{budget}"
                    val = results["ecdf"][key]
                    assert val >= prev - 1e-12, \
                        f"ECDF not monotonic at {key}: {val} < {prev}"
                    prev = val

    def test_ecdf_bounds(self, results):
        """ECDF values must be in [0, 1]."""
        for key, val in results["ecdf"].items():
            assert 0.0 <= val <= 1.0, f"ECDF {key}={val} out of [0,1]"

    def test_ecdf_at_zero_budget(self, results):
        """At the smallest budget (100), ECDF should be small."""
        for algo in ALGORITHMS:
            for dim in DIMENSIONS:
                key = f"{algo}_d{dim}_b100"
                val = results["ecdf"][key]
                assert val < 0.5, \
                    f"ECDF at b=100 should be small, got {val} for {key}"


# ---------------------------------------------------------------------------
# Ranking tests
# ---------------------------------------------------------------------------
class TestRankings:
    def test_ranking_all_groups(self, results):
        """Verify rankings match independent computation."""
        for group in FUNCTION_GROUPS:
            expected = _ref_rankings(group)
            actual = results["rankings"].get(group)
            assert actual is not None, f"Missing ranking for {group}"
            assert actual == expected, \
                f"Ranking for {group}: expected {expected}, got {actual}"

    def test_ranking_structure(self, results):
        """Each ranking must be a permutation of the algorithm list."""
        for group in FUNCTION_GROUPS:
            ranking = results["rankings"][group]
            assert sorted(ranking) == sorted(ALGORITHMS), \
                f"Ranking for {group} is not a permutation: {ranking}"

    def test_cmaes_best_on_high_conditioning(self, results):
        """CMA-ES should rank first on high-conditioning functions."""
        ranking = results["rankings"]["high_conditioning"]
        assert ranking[0] == "CMAES", \
            f"Expected CMAES first on high_conditioning, got {ranking}"


# ---------------------------------------------------------------------------
# Scaling exponent tests
# ---------------------------------------------------------------------------
class TestScaling:
    def test_scaling_all_values(self, results):
        """Verify all scaling exponents against independent computation."""
        mismatches = []
        for algo in ALGORITHMS:
            for func in FUNCTIONS:
                key = f"{algo}_f{func}"
                expected = _ref_scaling(algo, func)
                actual = results["scaling_exponents"].get(key)
                if expected is None:
                    if actual is not None:
                        mismatches.append(
                            f"{key}: expected null, got {actual}")
                else:
                    if actual is None:
                        mismatches.append(
                            f"{key}: expected {expected:.6f}, got null")
                    elif abs(actual - expected) > 1e-4:
                        mismatches.append(
                            f"{key}: expected {expected:.6f}, got {actual}")
        assert not mismatches, (
            f"{len(mismatches)} scaling mismatches:\n"
            + "\n".join(mismatches[:20]))

    def test_scaling_range(self, results):
        """Finite scaling exponents should be in a reasonable range."""
        for key, val in results["scaling_exponents"].items():
            if val is not None:
                assert 0.3 < val < 5.0, \
                    f"Scaling {key}={val} out of reasonable range (0.3, 5.0)"

    def test_scaling_null_cases(self, results):
        """Algorithms that never reach 1e-08 should have null exponent."""
        for algo in ALGORITHMS:
            for func in FUNCTIONS:
                key = f"{algo}_f{func}"
                expected = _ref_scaling(algo, func)
                actual = results["scaling_exponents"].get(key)
                if expected is None:
                    assert actual is None, \
                        f"{key}: should be null (fewer than 2 dims with " \
                        f"finite ERT at 1e-08)"


# ---------------------------------------------------------------------------
# Virtual Best Solver tests
# ---------------------------------------------------------------------------
class TestVBS:
    def test_vbs_ert_all_values(self, results):
        """Verify every VBS ERT value against independent computation."""
        mismatches = []
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    expected = _ref_vbs_ert(func, dim, target)
                    actual = results["vbs_ert"].get(key)
                    if expected is None:
                        if actual is not None:
                            mismatches.append(
                                f"{key}: expected null, got {actual}")
                    else:
                        if actual is None:
                            mismatches.append(
                                f"{key}: expected {expected}, got null")
                        elif abs(actual - expected) > 1e-6 * abs(expected) + 1e-10:
                            mismatches.append(
                                f"{key}: expected {expected}, got {actual}")
        assert not mismatches, (
            f"{len(mismatches)} VBS ERT mismatches:\n"
            + "\n".join(mismatches[:20]))

    def test_vbs_leq_individual(self, results):
        """VBS ERT must be <= every individual algorithm's ERT."""
        violations = []
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    vbs_key = f"f{func}_d{dim}_t{target}"
                    vbs_val = results["vbs_ert"].get(vbs_key)
                    if vbs_val is None:
                        continue
                    for algo in ALGORITHMS:
                        algo_key = f"{algo}_f{func}_d{dim}_t{target}"
                        algo_val = results["ert"].get(algo_key)
                        if algo_val is not None and vbs_val > algo_val + 1e-6:
                            violations.append(
                                f"VBS {vbs_key}={vbs_val} > "
                                f"{algo_key}={algo_val}")
        assert not violations, (
            f"{len(violations)} VBS > individual violations:\n"
            + "\n".join(violations[:20]))

    def test_vbs_null_when_all_null(self, results):
        """VBS should be null only when no algorithm reaches the target."""
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    vbs_val = results["vbs_ert"].get(key)
                    any_finite = any(
                        _ref_ert(algo, func, dim, target) is not None
                        for algo in ALGORITHMS
                    )
                    if any_finite:
                        assert vbs_val is not None, \
                            f"VBS {key} is null but some algorithm succeeds"
                    else:
                        assert vbs_val is None, \
                            f"VBS {key} is {vbs_val} but no algorithm succeeds"


# ---------------------------------------------------------------------------
# Algorithm selection tests
# ---------------------------------------------------------------------------
class TestAlgorithmSelection:
    def test_selection_all_values(self, results):
        """Verify algorithm selection matches independent computation."""
        mismatches = []
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    expected = _ref_algorithm_selection(func, dim, target)
                    actual = results["algorithm_selection"].get(key)
                    if expected != actual:
                        mismatches.append(
                            f"{key}: expected {expected}, got {actual}")
        assert not mismatches, (
            f"{len(mismatches)} selection mismatches:\n"
            + "\n".join(mismatches[:20]))

    def test_selection_consistent_with_vbs(self, results):
        """Selected algorithm's ERT must equal VBS ERT."""
        violations = []
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    sel = results["algorithm_selection"].get(key)
                    vbs_val = results["vbs_ert"].get(key)
                    if sel is None:
                        if vbs_val is not None:
                            violations.append(
                                f"{key}: sel=null but VBS={vbs_val}")
                        continue
                    algo_key = f"{sel}_f{func}_d{dim}_t{target}"
                    algo_val = results["ert"].get(algo_key)
                    if vbs_val is not None and algo_val is not None:
                        if abs(algo_val - vbs_val) > 1e-6 * abs(vbs_val) + 1e-10:
                            violations.append(
                                f"{key}: sel={sel} ERT={algo_val} "
                                f"!= VBS={vbs_val}")
        assert not violations, (
            f"{len(violations)} selection/VBS inconsistencies:\n"
            + "\n".join(violations[:20]))

    def test_selection_is_valid_algorithm(self, results):
        """Selected algorithm must be a known algorithm or null."""
        for func in FUNCTIONS:
            for dim in DIMENSIONS:
                for target in TARGETS:
                    key = f"f{func}_d{dim}_t{target}"
                    sel = results["algorithm_selection"].get(key)
                    if sel is not None:
                        assert sel in ALGORITHMS, \
                            f"Selection {key}={sel} not in {ALGORITHMS}"


# ---------------------------------------------------------------------------
# Performance profile tests
# ---------------------------------------------------------------------------
class TestPerformanceProfile:
    def test_profile_all_values(self, results):
        """Verify all performance profile values."""
        mismatches = []
        for algo in ALGORITHMS:
            for tau in PERF_THRESHOLDS:
                key = f"{algo}_tau{tau}"
                expected = _ref_performance_profile(algo, tau)
                actual = results["performance_profile"].get(key)
                if actual is None:
                    mismatches.append(f"{key}: missing")
                elif abs(actual - expected) > 1e-10:
                    mismatches.append(
                        f"{key}: expected {expected}, got {actual}")
        assert not mismatches, (
            f"{len(mismatches)} profile mismatches:\n"
            + "\n".join(mismatches[:20]))

    def test_profile_monotonic_in_tau(self, results):
        """Performance profile must be non-decreasing in tau."""
        for algo in ALGORITHMS:
            prev = -1.0
            for tau in PERF_THRESHOLDS:
                key = f"{algo}_tau{tau}"
                val = results["performance_profile"][key]
                assert val >= prev - 1e-12, \
                    f"Profile not monotonic at {key}: {val} < {prev}"
                prev = val

    def test_profile_bounds(self, results):
        """Profile values must be in [0, 1]."""
        for key, val in results["performance_profile"].items():
            assert 0.0 <= val <= 1.0, \
                f"Profile {key}={val} out of [0,1]"

    def test_profile_at_tau_one_leq_overall(self, results):
        """At tau=1.0, profile <= profile at higher tau."""
        for algo in ALGORITHMS:
            tau1_key = f"{algo}_tau1.0"
            tau10_key = f"{algo}_tau10.0"
            assert results["performance_profile"][tau1_key] <= \
                results["performance_profile"][tau10_key] + 1e-12, \
                f"Profile at tau=1 should be <= tau=10 for {algo}"
