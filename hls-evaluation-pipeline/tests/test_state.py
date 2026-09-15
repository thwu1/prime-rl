
"""Tests for the HLS evaluation pipeline report."""
import json
import os
import pytest
from math import comb


REPORT_PATH = "/app/output/report.json"


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        data = json.load(f)
    return data


# ------------------------------------------------------------------
# Expected ground truth
# ------------------------------------------------------------------
# Compilation: all candidates compile EXCEPT hamming_dist candidates 06-10
EXPECTED_COMPILATION = {
    "add_arrays": {f"candidate_{i:02d}": True for i in range(1, 11)},
    "dot_product": {f"candidate_{i:02d}": True for i in range(1, 11)},
    "find_max": {f"candidate_{i:02d}": True for i in range(1, 11)},
    "prefix_sum": {f"candidate_{i:02d}": True for i in range(1, 11)},
    "hamming_dist": {
        **{f"candidate_{i:02d}": True for i in range(1, 6)},
        **{f"candidate_{i:02d}": False for i in range(6, 11)},
    },
}

# Simulation pass/fail
EXPECTED_SIMULATION = {
    "add_arrays": {
        **{f"candidate_{i:02d}": True for i in range(1, 8)},
        **{f"candidate_{i:02d}": False for i in range(8, 11)},
    },
    "dot_product": {
        **{f"candidate_{i:02d}": True for i in range(1, 5)},
        **{f"candidate_{i:02d}": False for i in range(5, 11)},
    },
    "find_max": {
        **{f"candidate_{i:02d}": True for i in range(1, 9)},
        **{f"candidate_{i:02d}": False for i in range(9, 11)},
    },
    "prefix_sum": {
        "candidate_01": True,
        **{f"candidate_{i:02d}": False for i in range(2, 11)},
    },
    "hamming_dist": {f"candidate_{i:02d}": False for i in range(1, 11)},
}

# Pass counts per benchmark (n=10 each)
PASS_COUNTS = {
    "add_arrays": 7,
    "dot_product": 4,
    "find_max": 8,
    "prefix_sum": 1,
    "hamming_dist": 0,
}


def _pass_at_k(n, c, k):
    """Reference Pass@k computation."""
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------
class TestReportStructure:
    def test_report_exists(self, report):
        assert report is not None

    def test_top_level_keys(self, report):
        required = {
            "compilation", "simulation", "dse",
            "pass_at_k", "pareto_frontier", "ppa_normalization",
        }
        assert required.issubset(set(report.keys()))


class TestCompilation:
    def test_all_benchmarks_present(self, report):
        comp = report["compilation"]
        for bench in EXPECTED_COMPILATION:
            assert bench in comp, f"Missing benchmark: {bench}"

    def test_compilation_results(self, report):
        comp = report["compilation"]
        for bench, expected in EXPECTED_COMPILATION.items():
            for cand, should_compile in expected.items():
                actual = comp[bench].get(cand)
                assert actual == should_compile, (
                    f"{bench}/{cand}: expected compile={should_compile}, "
                    f"got {actual}"
                )


class TestSimulation:
    def test_simulation_results(self, report):
        sim = report["simulation"]
        for bench, expected in EXPECTED_SIMULATION.items():
            assert bench in sim, f"Missing benchmark in simulation: {bench}"
            for cand, should_pass in expected.items():
                actual = sim[bench].get(cand)
                assert actual == should_pass, (
                    f"{bench}/{cand}: expected sim={should_pass}, got {actual}"
                )


class TestDSE:
    def test_unconstrained_total(self, report):
        # 2*2*2*2*4*3*3*2*3 = 3456
        assert report["dse"]["unconstrained_total"] == 3456

    def test_constrained_total(self, report):
        # Three dependency constraints: pipeline_ii, array_partition_factor,
        # allocation_limit_add -> constrained total = 1440
        assert report["dse"]["total_configurations"] == 1440


class TestPassAtK:
    @pytest.mark.parametrize("bench,c", PASS_COUNTS.items())
    def test_pass_at_1(self, report, bench, c):
        expected = _pass_at_k(10, c, 1)
        actual = report["pass_at_k"]["per_benchmark"][bench]["pass_at_1"]
        assert abs(actual - expected) < 1e-6, (
            f"{bench} pass@1: expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("bench,c", PASS_COUNTS.items())
    def test_pass_at_5(self, report, bench, c):
        expected = _pass_at_k(10, c, 5)
        actual = report["pass_at_k"]["per_benchmark"][bench]["pass_at_5"]
        assert abs(actual - expected) < 1e-6, (
            f"{bench} pass@5: expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("bench,c", PASS_COUNTS.items())
    def test_pass_at_10(self, report, bench, c):
        expected = _pass_at_k(10, c, 10)
        actual = report["pass_at_k"]["per_benchmark"][bench]["pass_at_10"]
        assert abs(actual - expected) < 1e-6, (
            f"{bench} pass@10: expected {expected}, got {actual}"
        )

    def test_aggregate_pass_at_1(self, report):
        expected = sum(
            _pass_at_k(10, c, 1) for c in PASS_COUNTS.values()
        ) / len(PASS_COUNTS)
        actual = report["pass_at_k"]["aggregate"]["pass_at_1"]
        assert abs(actual - expected) < 1e-6

    def test_aggregate_pass_at_5(self, report):
        expected = sum(
            _pass_at_k(10, c, 5) for c in PASS_COUNTS.values()
        ) / len(PASS_COUNTS)
        actual = report["pass_at_k"]["aggregate"]["pass_at_5"]
        assert abs(actual - expected) < 1e-6

    def test_aggregate_pass_at_10(self, report):
        expected = sum(
            _pass_at_k(10, c, 10) for c in PASS_COUNTS.values()
        ) / len(PASS_COUNTS)
        actual = report["pass_at_k"]["aggregate"]["pass_at_10"]
        assert abs(actual - expected) < 1e-6


class TestParetoFrontier:
    def test_optimal_set(self, report):
        expected = ["d01", "d02", "d03", "d04", "d05"]
        actual = sorted(report["pareto_frontier"]["optimal_set"])
        assert actual == expected

    def test_num_dominated(self, report):
        assert report["pareto_frontier"]["num_dominated"] == 10


class TestPPANormalization:
    EXPECTED_PPA = {
        "add_arrays": {
            "lut_pct": 20.0,
            "ff_pct": 25.0,
            "latency_pct": -20.0,
            "power_pct": 20.0,
        },
        "dot_product": {
            "lut_pct": -10.0,
            "ff_pct": 6.25,
            "latency_pct": -10.0,
            "power_pct": 10.0,
        },
        "find_max": {
            "lut_pct": 10.0,
            "ff_pct": 10.0,
            "latency_pct": 20.0,
            "power_pct": -10.0,
        },
    }

    @pytest.mark.parametrize("bench", ["add_arrays", "dot_product", "find_max"])
    def test_ppa_differentials(self, report, bench):
        expected = self.EXPECTED_PPA[bench]
        actual = report["ppa_normalization"][bench]
        for metric in ["lut_pct", "ff_pct", "latency_pct", "power_pct"]:
            assert abs(actual[metric] - expected[metric]) < 0.01, (
                f"{bench} {metric}: expected {expected[metric]}, "
                f"got {actual[metric]}"
            )
