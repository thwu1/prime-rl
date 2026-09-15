
"""
Tests for the quantum resource estimation pipeline.

Verifies:
1. The C shared library (libqec.so) is compiled and returns correct values
2. The output JSON contains correct resource estimates for all algorithms
3. Optimal protocol selection is correct per algorithm
4. Physical consistency constraints hold
"""

import json
import os
import ctypes
import math
import pytest


RESULTS_PATH = "/app/output/results.json"

# Expected results with optimal protocol selection
EXPECTED = {
    "small_qpe": {
        "optimal_protocol": "15-to-1",
        "code_distance": 11,
        "distillation_level": 1,
        "total_t_count": 22000,
        "num_factories": 220,
        "data_qubits": 3630,
        "factory_qubits": 212960,
        "total_physical_qubits": 216590,
        "execution_time_us": 5500.0,
        "spacetime_volume": 1191245000.0,
    },
    "medium_chem": {
        "optimal_protocol": "20-to-4",
        "code_distance": 15,
        "distillation_level": 1,
        "total_t_count": 10500000,
        "num_factories": 3150,
        "data_qubits": 67500,
        "factory_qubits": 14175000,
        "total_physical_qubits": 14242500,
        "execution_time_us": 150000.0,
        "spacetime_volume": 2136375000000.0,
    },
    "large_factoring": {
        "optimal_protocol": "15-to-1",
        "code_distance": 19,
        "distillation_level": 2,
        "total_t_count": 1000000000,
        "num_factories": 100000,
        "data_qubits": 2166000,
        "factory_qubits": 577600000,
        "total_physical_qubits": 579766000,
        "execution_time_us": 1900000.0,
        "spacetime_volume": 1101555400000000.0,
    },
}


# ==================== C Library Tests ====================

class TestCLibrary:
    """Verify the compiled C library exports correct functions."""

    @pytest.fixture(scope="class")
    def lib(self):
        for path in ["/app/src/libqec.so", "/app/libqec.so"]:
            if os.path.exists(path):
                lib = ctypes.CDLL(path)
                # Configure function signatures
                lib.logical_error_rate.argtypes = [
                    ctypes.c_double, ctypes.c_double, ctypes.c_int
                ]
                lib.logical_error_rate.restype = ctypes.c_double

                lib.distillation_error_15to1.argtypes = [
                    ctypes.c_double, ctypes.c_int
                ]
                lib.distillation_error_15to1.restype = ctypes.c_double

                lib.distillation_error_20to4.argtypes = [
                    ctypes.c_double, ctypes.c_int
                ]
                lib.distillation_error_20to4.restype = ctypes.c_double

                lib.find_code_distance.argtypes = [
                    ctypes.c_double, ctypes.c_double,
                    ctypes.c_int, ctypes.c_int, ctypes.c_double
                ]
                lib.find_code_distance.restype = ctypes.c_int

                lib.find_distillation_level_15to1.argtypes = [
                    ctypes.c_double, ctypes.c_longlong, ctypes.c_double
                ]
                lib.find_distillation_level_15to1.restype = ctypes.c_int

                lib.find_distillation_level_20to4.argtypes = [
                    ctypes.c_double, ctypes.c_longlong, ctypes.c_double
                ]
                lib.find_distillation_level_20to4.restype = ctypes.c_int

                return lib
        pytest.fail(
            "libqec.so not found at /app/src/libqec.so or /app/libqec.so. "
            "The C library must be compiled as a shared object."
        )

    def test_logical_error_rate_d3(self, lib):
        """p_L(d=3) = 0.1 * (0.1)^2 = 0.001"""
        result = lib.logical_error_rate(0.001, 0.01, 3)
        assert abs(result - 0.001) / 0.001 < 1e-6

    def test_logical_error_rate_d11(self, lib):
        """p_L(d=11) = 0.1 * (0.1)^6 = 1e-7"""
        result = lib.logical_error_rate(0.001, 0.01, 11)
        assert abs(result - 1e-7) / 1e-7 < 1e-6

    def test_logical_error_rate_d19(self, lib):
        """p_L(d=19) = 0.1 * (0.1)^10 = 1e-11"""
        result = lib.logical_error_rate(0.001, 0.01, 19)
        assert abs(result - 1e-11) / 1e-11 < 1e-6

    def test_distillation_15to1_k1(self, lib):
        """p_T(1) = 35 * 0.001^3 = 3.5e-8"""
        result = lib.distillation_error_15to1(0.001, 1)
        assert abs(result - 3.5e-8) / 3.5e-8 < 1e-6

    def test_distillation_15to1_k2(self, lib):
        """p_T(2) = 35 * (3.5e-8)^3"""
        p_t1 = 3.5e-8
        expected = 35.0 * p_t1 ** 3
        result = lib.distillation_error_15to1(0.001, 2)
        assert abs(result - expected) / expected < 1e-6

    def test_distillation_20to4_k1(self, lib):
        """p_T(1) = 56 * 0.001^4 = 5.6e-11"""
        result = lib.distillation_error_20to4(0.001, 1)
        assert abs(result - 5.6e-11) / 5.6e-11 < 1e-6

    def test_find_code_distance_small(self, lib):
        """small_qpe should get d=11"""
        d = lib.find_code_distance(0.001, 0.01, 10, 500, 0.01 / 3.0)
        assert d == 11

    def test_find_code_distance_large(self, lib):
        """large_factoring should get d=19"""
        d = lib.find_code_distance(0.001, 0.01, 2000, 100000, 0.01 / 3.0)
        assert d == 19

    def test_find_distillation_15to1(self, lib):
        """small_qpe with 15-to-1: k=1"""
        k = lib.find_distillation_level_15to1(0.001, 22000, 0.01 / 3.0)
        assert k == 1

    def test_find_distillation_20to4(self, lib):
        """medium_chem with 20-to-4: k=1"""
        k = lib.find_distillation_level_20to4(0.001, 10500000, 0.01 / 3.0)
        assert k == 1


# ==================== Output Structure Tests ====================

class TestOutputStructure:
    """Verify the output file exists and has correct structure."""

    @pytest.fixture(scope="class")
    def results(self):
        assert os.path.exists(RESULTS_PATH), (
            f"Output file {RESULTS_PATH} does not exist"
        )
        with open(RESULTS_PATH, "r") as f:
            data = json.load(f)
        assert isinstance(data, list), "results.json must contain a JSON array"
        return {entry["name"]: entry for entry in data}

    def test_all_algorithms_present(self, results):
        for name in EXPECTED:
            assert name in results, f"Algorithm '{name}' missing from output"

    def test_no_extra_algorithms(self, results):
        for name in results:
            assert name in EXPECTED, f"Unexpected algorithm '{name}'"

    def test_required_fields(self, results):
        required = [
            "name", "optimal_protocol", "total_t_count", "code_distance",
            "distillation_level", "num_factories", "data_qubits",
            "factory_qubits", "total_physical_qubits",
            "execution_time_us", "spacetime_volume",
        ]
        for algo_name, entry in results.items():
            for field in required:
                assert field in entry, (
                    f"{algo_name}: missing required field '{field}'"
                )

    def test_integer_fields_are_integers(self, results):
        int_fields = [
            "total_t_count", "code_distance", "distillation_level",
            "num_factories", "data_qubits", "factory_qubits",
            "total_physical_qubits",
        ]
        for algo_name, entry in results.items():
            for field in int_fields:
                val = entry[field]
                assert isinstance(val, int) or (
                    isinstance(val, float) and val == int(val)
                ), f"{algo_name}: {field} = {val} should be an integer"

    def test_code_distance_is_odd(self, results):
        for algo_name, entry in results.items():
            d = int(entry["code_distance"])
            assert d % 2 == 1, f"{algo_name}: d={d} must be odd"
            assert d >= 3, f"{algo_name}: d={d} must be >= 3"

    def test_protocol_is_valid(self, results):
        for algo_name, entry in results.items():
            assert entry["optimal_protocol"] in ("15-to-1", "20-to-4"), (
                f"{algo_name}: invalid protocol '{entry['optimal_protocol']}'"
            )


# ==================== Correctness Tests ====================

@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"{RESULTS_PATH} does not exist"
    with open(RESULTS_PATH, "r") as f:
        data = json.load(f)
    return {entry["name"]: entry for entry in data}


@pytest.mark.parametrize("algo_name", list(EXPECTED.keys()))
class TestAlgorithmResults:
    """Verify exact resource estimates for each algorithm."""

    def test_optimal_protocol(self, results, algo_name):
        expected = EXPECTED[algo_name]["optimal_protocol"]
        actual = results[algo_name]["optimal_protocol"]
        assert actual == expected, (
            f"{algo_name}: protocol={actual}, expected {expected}"
        )

    def test_total_t_count(self, results, algo_name):
        expected = EXPECTED[algo_name]["total_t_count"]
        actual = results[algo_name]["total_t_count"]
        assert actual == expected, (
            f"{algo_name}: total_t_count={actual}, expected {expected}"
        )

    def test_code_distance(self, results, algo_name):
        expected = EXPECTED[algo_name]["code_distance"]
        actual = results[algo_name]["code_distance"]
        assert actual == expected, (
            f"{algo_name}: code_distance={actual}, expected {expected}"
        )

    def test_distillation_level(self, results, algo_name):
        expected = EXPECTED[algo_name]["distillation_level"]
        actual = results[algo_name]["distillation_level"]
        assert actual == expected, (
            f"{algo_name}: distillation_level={actual}, expected {expected}"
        )

    def test_num_factories(self, results, algo_name):
        expected = EXPECTED[algo_name]["num_factories"]
        actual = results[algo_name]["num_factories"]
        assert actual == expected, (
            f"{algo_name}: num_factories={actual}, expected {expected}"
        )

    def test_data_qubits(self, results, algo_name):
        expected = EXPECTED[algo_name]["data_qubits"]
        actual = results[algo_name]["data_qubits"]
        assert actual == expected, (
            f"{algo_name}: data_qubits={actual}, expected {expected}"
        )

    def test_factory_qubits(self, results, algo_name):
        expected = EXPECTED[algo_name]["factory_qubits"]
        actual = results[algo_name]["factory_qubits"]
        assert actual == expected, (
            f"{algo_name}: factory_qubits={actual}, expected {expected}"
        )

    def test_total_physical_qubits(self, results, algo_name):
        expected = EXPECTED[algo_name]["total_physical_qubits"]
        actual = results[algo_name]["total_physical_qubits"]
        assert actual == expected, (
            f"{algo_name}: total_physical_qubits={actual}, expected {expected}"
        )

    def test_execution_time(self, results, algo_name):
        expected = EXPECTED[algo_name]["execution_time_us"]
        actual = results[algo_name]["execution_time_us"]
        assert abs(actual - expected) / max(abs(expected), 1e-15) < 1e-6, (
            f"{algo_name}: execution_time_us={actual}, expected {expected}"
        )

    def test_spacetime_volume(self, results, algo_name):
        expected = EXPECTED[algo_name]["spacetime_volume"]
        actual = results[algo_name]["spacetime_volume"]
        assert abs(actual - expected) / max(abs(expected), 1e-15) < 1e-6, (
            f"{algo_name}: spacetime_volume={actual}, expected {expected}"
        )


# ==================== Physics Consistency Tests ====================

class TestPhysicsConsistency:
    """Cross-check that results satisfy physical constraints."""

    @pytest.fixture(scope="class")
    def res(self):
        with open(RESULTS_PATH, "r") as f:
            data = json.load(f)
        return {entry["name"]: entry for entry in data}

    def test_qubit_additivity(self, res):
        """data_qubits + factory_qubits == total_physical_qubits"""
        for name, entry in res.items():
            q_data = int(entry["data_qubits"])
            q_fac = int(entry["factory_qubits"])
            q_total = int(entry["total_physical_qubits"])
            assert q_data + q_fac == q_total, (
                f"{name}: {q_data} + {q_fac} != {q_total}"
            )

    def test_spacetime_equals_qubits_times_time(self, res):
        """V = q_total * t_algorithm"""
        for name, entry in res.items():
            q = entry["total_physical_qubits"]
            t = entry["execution_time_us"]
            v = entry["spacetime_volume"]
            expected_v = q * t
            assert abs(v - expected_v) / max(abs(expected_v), 1e-15) < 1e-6, (
                f"{name}: V={v} != q*t={expected_v}"
            )

    def test_monotone_qubits(self, res):
        """Larger algorithms need more qubits."""
        q_small = res["small_qpe"]["total_physical_qubits"]
        q_med = res["medium_chem"]["total_physical_qubits"]
        q_large = res["large_factoring"]["total_physical_qubits"]
        assert q_small < q_med < q_large

    def test_monotone_code_distance(self, res):
        """Larger algorithms need equal or higher code distance."""
        d_small = res["small_qpe"]["code_distance"]
        d_med = res["medium_chem"]["code_distance"]
        d_large = res["large_factoring"]["code_distance"]
        assert d_small <= d_med <= d_large
