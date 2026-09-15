
"""Tests for multi-backend quantum error correction pipeline."""

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_code(code_name):
    return load_json(f"/app/codes/{code_name}.json")


def gf2_rank(M):
    """Compute rank of binary matrix over GF(2)."""
    A = np.array(M, dtype=np.int8).copy()
    rows, cols = A.shape
    rank = 0
    for col in range(cols):
        pivot = None
        for row in range(rank, rows):
            if A[row, col] == 1:
                pivot = row
                break
        if pivot is None:
            continue
        A[[rank, pivot]] = A[[pivot, rank]]
        for row in range(rows):
            if row != rank and A[row, col] == 1:
                A[row] = (A[row] + A[rank]) % 2
        rank += 1
    return rank


def get_check_matrix(code_data, error_type):
    """Z errors detected by Hx, X errors detected by Hz."""
    key = "Hx" if error_type == "Z" else "Hz"
    return np.array(code_data[key], dtype=np.int8)


def get_logical_check(code_data, error_type):
    """Z logical errors checked by Lx, X logical errors checked by Lz."""
    key = "Lx" if error_type == "Z" else "Lz"
    return np.array(code_data[key], dtype=np.int8)


def has_lower_weight_correction(H, syndrome, max_weight):
    """Check if any correction of weight < max_weight resolves the syndrome."""
    n = H.shape[1]
    for w in range(max_weight):
        if w == 0:
            if np.all(syndrome == 0):
                return True
            continue
        for combo in combinations(range(n), w):
            c = np.zeros(n, dtype=np.int8)
            for idx in combo:
                c[idx] = 1
            if np.array_equal(H @ c % 2, syndrome):
                return True
    return False


def get_code_data_for_task(task):
    """Load code data, handling hamming15 from results."""
    code_name = task["code"]
    if code_name == "hamming15":
        results = load_json("/app/results.json")
        params = results["code_params"]["hamming15"]
        return {
            "n": params["n"],
            "k": params["k"],
            "d": params["d"],
            "Hx": params["Hx"],
            "Hz": params["Hz"],
            "Lx": params["Lx"],
            "Lz": params["Lz"],
        }
    return load_code(code_name)


@pytest.fixture(scope="module")
def results():
    return load_json("/app/results.json")


@pytest.fixture(scope="module")
def tasks():
    return load_json("/app/tasks.json")


@pytest.fixture(scope="module")
def hamming15_params(results):
    return results["code_params"]["hamming15"]


# ─── Structure Tests ──────────────────────────────────────────────

class TestResultsStructure:
    def test_results_file_exists(self):
        assert Path("/app/results.json").exists(), "results.json not found"

    def test_top_level_keys(self, results):
        assert "code_params" in results, "Missing code_params"
        assert "decoding_results" in results, "Missing decoding_results"
        assert "simulation_results" in results, "Missing simulation_results"

    def test_hamming15_in_code_params(self, results):
        assert "hamming15" in results["code_params"], "Missing hamming15 in code_params"

    def test_all_decoding_tasks_present(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            assert task["id"] in results["decoding_results"], (
                f"Missing decoding result for {task['id']}"
            )

    def test_all_simulation_tasks_present(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            assert task["id"] in results["simulation_results"], (
                f"Missing simulation result for {task['id']}"
            )

    def test_dual_backend_structure(self, results, tasks):
        """Non-weighted decoding tasks must have both maxsat and bposd results."""
        for task in tasks["decoding_tasks"]:
            if task.get("weighted", False):
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]
            assert "maxsat" in r, f"{tid}: missing maxsat result"
            assert "bposd" in r, f"{tid}: missing bposd result"

    def test_weighted_tasks_maxsat_only(self, results, tasks):
        """Weighted tasks should have maxsat but not require bposd."""
        for task in tasks["decoding_tasks"]:
            if not task.get("weighted", False):
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]
            assert "maxsat" in r, f"{tid}: missing maxsat result for weighted task"


# ─── Hamming15 Code Parameter Tests ──────────────────────────────

class TestHamming15CodeParams:
    def test_n(self, hamming15_params):
        assert hamming15_params["n"] == 15

    def test_k(self, hamming15_params):
        assert hamming15_params["k"] == 7

    def test_d(self, hamming15_params):
        assert hamming15_params["d"] == 3

    def test_hx_shape(self, hamming15_params):
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        assert Hx.shape == (4, 15), f"Hx shape {Hx.shape} != (4, 15)"

    def test_hz_shape(self, hamming15_params):
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        assert Hz.shape == (4, 15), f"Hz shape {Hz.shape} != (4, 15)"

    def test_lx_shape(self, hamming15_params):
        Lx = np.array(hamming15_params["Lx"], dtype=np.int8)
        assert Lx.shape[0] == 7, f"Lx should have 7 rows, got {Lx.shape[0]}"
        assert Lx.shape[1] == 15, f"Lx should have 15 cols, got {Lx.shape[1]}"

    def test_lz_shape(self, hamming15_params):
        Lz = np.array(hamming15_params["Lz"], dtype=np.int8)
        assert Lz.shape[0] == 7, f"Lz should have 7 rows, got {Lz.shape[0]}"
        assert Lz.shape[1] == 15, f"Lz should have 15 cols, got {Lz.shape[1]}"

    def test_hx_rank(self, hamming15_params):
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        assert gf2_rank(Hx) == 4

    def test_hz_rank(self, hamming15_params):
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        assert gf2_rank(Hz) == 4

    def test_k_from_ranks(self, hamming15_params):
        """k = n - rank(Hx) - rank(Hz)."""
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        computed_k = 15 - gf2_rank(Hx) - gf2_rank(Hz)
        assert computed_k == 7, f"k = {computed_k} != 7"


# ─── CSS Property Tests ──────────────────────────────────────────

class TestCSSProperties:
    @pytest.mark.parametrize("code_name", ["steane", "shor"])
    def test_known_css_orthogonality(self, code_name):
        code = load_code(code_name)
        Hx = np.array(code["Hx"], dtype=np.int8)
        Hz = np.array(code["Hz"], dtype=np.int8)
        product = Hx @ Hz.T % 2
        assert np.all(product == 0), f"{code_name}: Hx @ Hz^T != 0 mod 2"

    def test_hamming15_css_orthogonality(self, hamming15_params):
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        product = Hx @ Hz.T % 2
        assert np.all(product == 0), "hamming15: Hx @ Hz^T != 0 mod 2"

    def test_hamming15_logical_commutation_with_stabilizers(self, hamming15_params):
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        Lx = np.array(hamming15_params["Lx"], dtype=np.int8)
        Lz = np.array(hamming15_params["Lz"], dtype=np.int8)
        # Lx must commute with Hz
        assert np.all(Hz @ Lx.T % 2 == 0), "Lx doesn't commute with Hz"
        # Lz must commute with Hx
        assert np.all(Hx @ Lz.T % 2 == 0), "Lz doesn't commute with Hx"

    def test_hamming15_logical_anticommutation(self, hamming15_params):
        """Lx @ Lz^T should be identity matrix mod 2."""
        Lx = np.array(hamming15_params["Lx"], dtype=np.int8)
        Lz = np.array(hamming15_params["Lz"], dtype=np.int8)
        overlap = Lx @ Lz.T % 2
        expected = np.eye(7, dtype=np.int8)
        assert np.array_equal(overlap, expected), (
            f"Lx @ Lz^T != I_7, got:\n{overlap}"
        )

    def test_hamming15_logicals_not_stabilizers(self, hamming15_params):
        """Each logical operator should NOT be in the stabilizer row space."""
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        Lx = np.array(hamming15_params["Lx"], dtype=np.int8)
        Lz = np.array(hamming15_params["Lz"], dtype=np.int8)
        hx_rank = gf2_rank(Hx)
        hz_rank = gf2_rank(Hz)
        for i in range(7):
            # Lx[i] should NOT be in rowspace(Hx)
            test = np.vstack([Hx, Lx[i:i+1]])
            assert gf2_rank(test) > hx_rank, f"Lx[{i}] is in rowspace(Hx)"
            # Lz[i] should NOT be in rowspace(Hz)
            test = np.vstack([Hz, Lz[i:i+1]])
            assert gf2_rank(test) > hz_rank, f"Lz[{i}] is in rowspace(Hz)"

    def test_hamming15_distance_verification(self, hamming15_params):
        """Verify no weight-1 or weight-2 non-trivial logicals exist."""
        Hx = np.array(hamming15_params["Hx"], dtype=np.int8)
        Hz = np.array(hamming15_params["Hz"], dtype=np.int8)
        n = 15
        hx_rank = gf2_rank(Hx)
        hz_rank = gf2_rank(Hz)
        for w in range(1, 3):
            for combo in combinations(range(n), w):
                v = np.zeros(n, dtype=np.int8)
                for idx in combo:
                    v[idx] = 1
                # Check Z-type logical: in ker(Hx) and not in rowspace(Hz)
                if np.all(Hx @ v % 2 == 0):
                    test = np.vstack([Hz, v.reshape(1, -1)])
                    assert gf2_rank(test) == hz_rank, (
                        f"Found weight-{w} Z-logical at positions {combo}"
                    )
                # Check X-type logical: in ker(Hz) and not in rowspace(Hx)
                if np.all(Hz @ v % 2 == 0):
                    test = np.vstack([Hx, v.reshape(1, -1)])
                    assert gf2_rank(test) == hx_rank, (
                        f"Found weight-{w} X-logical at positions {combo}"
                    )


# ─── MaxSAT Decoding Tests ───────────────────────────────────────

class TestMaxSATSyndromeResolution:
    """Every MaxSAT correction must resolve its syndrome."""

    def test_all_maxsat_corrections_resolve(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            code = get_code_data_for_task(task)
            H = get_check_matrix(code, task["error_type"])
            error = np.array(task["error"], dtype=np.int8)
            correction = np.array(r["correction"], dtype=np.int8)
            syndrome = H @ error % 2
            correction_syndrome = H @ correction % 2
            assert np.array_equal(correction_syndrome, syndrome), (
                f"{tid} maxsat: syndrome not resolved"
            )
            assert r["syndrome_resolved"] is True


class TestMaxSATOptimality:
    """MaxSAT corrections must have minimum weight."""

    def test_maxsat_weight_consistency(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            correction = np.array(r["correction"], dtype=np.int8)
            assert int(np.sum(correction)) == r["weight"], (
                f"{tid}: reported weight doesn't match correction vector"
            )

    def test_maxsat_no_lower_weight_exists(self, results, tasks):
        """For unweighted tasks, verify no lower-weight correction exists."""
        for task in tasks["decoding_tasks"]:
            if task.get("weighted", False):
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            code = get_code_data_for_task(task)
            H = get_check_matrix(code, task["error_type"])
            error = np.array(task["error"], dtype=np.int8)
            syndrome = H @ error % 2
            weight = r["weight"]
            assert not has_lower_weight_correction(H, syndrome, weight), (
                f"{tid}: found correction with weight < {weight}"
            )


class TestMaxSATLogicalErrors:
    """Logical error flags must be correct for MaxSAT."""

    def test_maxsat_logical_error_matches_residual(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            code = get_code_data_for_task(task)
            L = get_logical_check(code, task["error_type"])
            error = np.array(task["error"], dtype=np.int8)
            correction = np.array(r["correction"], dtype=np.int8)
            residual = (error + correction) % 2
            expected = bool((L @ residual % 2).any())
            assert r["is_logical_error"] == expected, (
                f"{tid} maxsat: is_logical_error={r['is_logical_error']}, "
                f"expected={expected}"
            )


# ─── BP+OSD Decoding Tests ───────────────────────────────────────

class TestBpOsdSyndromeResolution:
    """Every BP+OSD correction must resolve its syndrome."""

    def test_all_bposd_corrections_resolve(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            if task.get("weighted", False):
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["bposd"]
            code = get_code_data_for_task(task)
            H = get_check_matrix(code, task["error_type"])
            error = np.array(task["error"], dtype=np.int8)
            correction = np.array(r["correction"], dtype=np.int8)
            syndrome = H @ error % 2
            correction_syndrome = H @ correction % 2
            assert np.array_equal(correction_syndrome, syndrome), (
                f"{tid} bposd: syndrome not resolved"
            )
            assert r["syndrome_resolved"] is True


class TestBpOsdWeightConsistency:
    def test_bposd_weight_matches_correction(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            if task.get("weighted", False):
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["bposd"]
            correction = np.array(r["correction"], dtype=np.int8)
            assert int(np.sum(correction)) == r["weight"], (
                f"{tid} bposd: weight mismatch"
            )


class TestBpOsdLogicalErrors:
    """Logical error flags must be correct for BP+OSD."""

    def test_bposd_logical_error_matches_residual(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            if task.get("weighted", False):
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["bposd"]
            code = get_code_data_for_task(task)
            L = get_logical_check(code, task["error_type"])
            error = np.array(task["error"], dtype=np.int8)
            correction = np.array(r["correction"], dtype=np.int8)
            residual = (error + correction) % 2
            expected = bool((L @ residual % 2).any())
            assert r["is_logical_error"] == expected, (
                f"{tid} bposd: is_logical_error={r['is_logical_error']}, "
                f"expected={expected}"
            )


# ─── Code-Specific Tests ─────────────────────────────────────────

class TestSteaneCodeSpecific:
    def test_single_qubit_maxsat_matches_error(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            if task["code"] != "steane" or task.get("weighted", False):
                continue
            error = task["error"]
            if sum(error) != 1:
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            assert r["weight"] == 1, f"{tid}: maxsat weight != 1"
            assert r["correction"] == error, f"{tid}: maxsat correction != error"
            assert r["is_logical_error"] is False

    def test_weight2_errors_cause_logical_errors(self, results, tasks):
        for task in tasks["decoding_tasks"]:
            if task["code"] != "steane" or task.get("weighted", False):
                continue
            if sum(task["error"]) != 2:
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            assert r["weight"] == 1
            assert r["is_logical_error"] is True

    def test_logical_operator_error(self, results):
        r = results["decoding_results"]["steane_z_logical"]["maxsat"]
        assert r["weight"] == 0
        assert r["is_logical_error"] is True


class TestShorCodeSpecific:
    def test_z_single_corrections(self, results):
        for tid in ["shor_z_single_q0", "shor_z_single_q4"]:
            r = results["decoding_results"][tid]["maxsat"]
            assert r["weight"] == 1
            assert r["is_logical_error"] is False

    def test_z_weight2_logical(self, results):
        r = results["decoding_results"]["shor_z_weight2_q02"]["maxsat"]
        assert r["weight"] == 1
        assert r["is_logical_error"] is True

    def test_x_single_valid(self, results):
        r = results["decoding_results"]["shor_x_single_q0"]["maxsat"]
        assert r["weight"] == 1
        assert r["syndrome_resolved"] is True
        assert r["is_logical_error"] is False

    def test_x_weight2_logical(self, results):
        r = results["decoding_results"]["shor_x_weight2_q03"]["maxsat"]
        assert r["weight"] == 1
        assert r["is_logical_error"] is True


class TestHamming15Specific:
    """Tests specific to the [[15,7,3]] quantum Hamming code."""

    def test_single_qubit_corrections(self, results):
        """Single-qubit errors should have unique weight-1 corrections."""
        for tid in ["hamming15_z_single_q0", "hamming15_z_single_q7",
                     "hamming15_x_single_q3"]:
            for backend in ["maxsat", "bposd"]:
                r = results["decoding_results"][tid][backend]
                assert r["weight"] == 1, f"{tid} {backend}: weight != 1"
                assert r["is_logical_error"] is False, (
                    f"{tid} {backend}: should not be logical error"
                )

    def test_single_qubit_maxsat_matches_error(self, results, tasks):
        """For Hamming code, single-qubit MaxSAT correction equals the error."""
        for task in tasks["decoding_tasks"]:
            if task["code"] != "hamming15":
                continue
            if sum(task["error"]) != 1:
                continue
            tid = task["id"]
            r = results["decoding_results"][tid]["maxsat"]
            assert r["correction"] == task["error"], (
                f"{tid}: maxsat correction should equal error"
            )

    def test_weight2_causes_logical_error(self, results):
        """Weight-2 errors on Hamming code cause logical errors."""
        for tid in ["hamming15_z_weight2_q01", "hamming15_x_weight2_q37"]:
            r = results["decoding_results"][tid]["maxsat"]
            assert r["weight"] == 1, f"{tid}: should decode to weight-1"
            assert r["is_logical_error"] is True, (
                f"{tid}: weight-2 error should cause logical error"
            )


class TestWeightedDecoding:
    def test_weighted_correction_valid(self, results):
        r = results["decoding_results"]["steane_z_weighted_q01"]["maxsat"]
        code = load_code("steane")
        H = np.array(code["Hx"], dtype=np.int8)
        error = np.array([1, 1, 0, 0, 0, 0, 0], dtype=np.int8)
        correction = np.array(r["correction"], dtype=np.int8)
        syndrome = H @ error % 2
        assert np.array_equal(H @ correction % 2, syndrome)
        assert r["syndrome_resolved"] is True

    def test_weighted_prefers_likely_error(self, results):
        r = results["decoding_results"]["steane_z_weighted_q01"]["maxsat"]
        assert r["correction"] == [1, 1, 0, 0, 0, 0, 0], (
            "Weighted decoder should prefer flipping high-error-rate qubits"
        )
        assert r["is_logical_error"] is False


# ─── Simulation Tests ─────────────────────────────────────────────

class TestSimulationResults:
    def test_simulation_fields(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            tid = task["id"]
            sim = results["simulation_results"][tid]
            assert "error_rate" in sim
            assert "num_trials" in sim
            assert "maxsat_logical_error_rate" in sim
            assert "maxsat_num_logical_errors" in sim
            assert "bposd_logical_error_rate" in sim
            assert "bposd_num_logical_errors" in sim

    def test_simulation_trial_counts(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            tid = task["id"]
            sim = results["simulation_results"][tid]
            assert sim["num_trials"] == task["num_trials"]

    def test_simulation_error_rate_recorded(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            tid = task["id"]
            sim = results["simulation_results"][tid]
            assert abs(sim["error_rate"] - task["error_rate"]) < 1e-9

    def test_simulation_rates_bounded(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            tid = task["id"]
            sim = results["simulation_results"][tid]
            for key in ["maxsat_logical_error_rate", "bposd_logical_error_rate"]:
                assert 0.0 <= sim[key] <= 1.0, f"{tid}: {key} out of [0,1]"

    def test_steane_low_error_rate(self, results):
        sim = results["simulation_results"]["steane_sim_low"]
        assert sim["maxsat_logical_error_rate"] < 0.1
        assert sim["bposd_logical_error_rate"] < 0.1

    def test_steane_high_error_rate(self, results):
        sim = results["simulation_results"]["steane_sim_high"]
        assert sim["maxsat_logical_error_rate"] > 0.01
        assert sim["bposd_logical_error_rate"] > 0.01

    def test_maxsat_logical_errors_consistent(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            tid = task["id"]
            sim = results["simulation_results"][tid]
            expected = sim["maxsat_num_logical_errors"] / sim["num_trials"]
            assert abs(sim["maxsat_logical_error_rate"] - expected) < 1e-9

    def test_bposd_logical_errors_consistent(self, results, tasks):
        for task in tasks["simulation_tasks"]:
            tid = task["id"]
            sim = results["simulation_results"][tid]
            expected = sim["bposd_num_logical_errors"] / sim["num_trials"]
            assert abs(sim["bposd_logical_error_rate"] - expected) < 1e-9
