"""Tests for quantum error mitigation benchmark pipeline.

"""
import json
import os
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")

from simulator import load_circuit, simulate


BENCHMARK_SCRIPT = "/app/run_benchmark.py"
RESULTS_PATH = "/app/results/benchmark.json"
CIRCUITS_DIR = "/app/circuits"


# ===== Benchmark Pipeline Tests (original circuits) =====


class TestBenchmarkPipeline:
    @pytest.fixture(autouse=True, scope="class")
    def run_benchmark(self):
        result = subprocess.run(
            [sys.executable, BENCHMARK_SCRIPT],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, f"Benchmark script failed:\n{result.stderr}"

    def _load_results(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_has_all_circuits(self):
        results = self._load_results()
        assert len(results) >= 4, f"Expected >= 4 circuits, got {len(results)}"

    def test_required_fields(self):
        results = self._load_results()
        required = [
            "ideal",
            "unmitigated",
            "scale_factors",
            "noisy_values",
            "richardson",
            "polynomial_2",
            "exponential",
            "best_method",
        ]
        for cid, entry in results.items():
            for field in required:
                assert field in entry, f"Missing '{field}' in circuit '{cid}'"

    def test_scale_factors_correct(self):
        results = self._load_results()
        for cid, entry in results.items():
            assert entry["scale_factors"] == [1, 3, 5], (
                f"Wrong scale_factors for {cid}"
            )
            assert len(entry["noisy_values"]) == 3

    def test_ideal_values(self):
        results = self._load_results()
        for cid, entry in results.items():
            assert abs(entry["ideal"] - 1.0) < 1e-9, (
                f"Ideal value for '{cid}' should be 1.0, got {entry['ideal']}"
            )

    def test_unmitigated_below_ideal(self):
        results = self._load_results()
        for cid, entry in results.items():
            assert entry["unmitigated"] < entry["ideal"], (
                f"Unmitigated should be below ideal for '{cid}'"
            )

    def test_noisy_values_decrease(self):
        results = self._load_results()
        for cid, entry in results.items():
            nv = entry["noisy_values"]
            assert nv[0] > nv[1] > nv[2], (
                f"Noisy values should decrease for '{cid}': {nv}"
            )

    def test_noisy_value_at_sf1_matches_unmitigated(self):
        """noisy_values[0] at scale_factor=1 should equal unmitigated."""
        results = self._load_results()
        for cid, entry in results.items():
            assert abs(entry["noisy_values"][0] - entry["unmitigated"]) < 1e-9, (
                f"noisy_values[0] != unmitigated for '{cid}'"
            )

    def test_unmitigated_matches_simulator(self):
        """Verify unmitigated values match direct simulation at noise_level=0.01."""
        results = self._load_results()
        for fname in sorted(os.listdir(CIRCUITS_DIR)):
            if not fname.endswith(".json"):
                continue
            circuit = load_circuit(os.path.join(CIRCUITS_DIR, fname))
            cid = circuit["id"]
            if cid in results:
                expected = simulate(circuit, noise_level=0.01)
                assert abs(results[cid]["unmitigated"] - expected) < 1e-9, (
                    f"Unmitigated mismatch for '{cid}': "
                    f"got {results[cid]['unmitigated']}, expected {expected}"
                )

    def test_all_methods_improve(self):
        """Every corrected estimate must improve over unmitigated."""
        results = self._load_results()
        for cid, entry in results.items():
            ideal = entry["ideal"]
            unmit_err = abs(entry["unmitigated"] - ideal)
            for method in ["richardson", "polynomial_2", "exponential"]:
                method_err = abs(entry[method] - ideal)
                assert method_err < unmit_err, (
                    f"'{method}' did not improve for '{cid}': "
                    f"method_err={method_err:.6f}, unmit_err={unmit_err:.6f}"
                )

    def test_exponential_close_to_ideal_1qubit(self):
        """Exponential should be close to ideal for 1-qubit depolarizing circuits."""
        results = self._load_results()
        one_qubit_ids = ["identity_x20", "identity_h40", "identity_s20"]
        for cid, entry in results.items():
            if cid in one_qubit_ids:
                assert abs(entry["exponential"] - 1.0) < 0.05, (
                    f"Exponential for '{cid}' too far from ideal: "
                    f"{entry['exponential']}"
                )

    def test_best_method_valid(self):
        results = self._load_results()
        valid_methods = {"richardson", "polynomial_2", "exponential"}
        for cid, entry in results.items():
            assert entry["best_method"] in valid_methods, (
                f"Invalid best_method '{entry['best_method']}' for '{cid}'"
            )

    def test_best_method_is_closest(self):
        """best_method should be the method closest to ideal."""
        results = self._load_results()
        for cid, entry in results.items():
            ideal = entry["ideal"]
            methods = {
                "richardson": entry["richardson"],
                "polynomial_2": entry["polynomial_2"],
                "exponential": entry["exponential"],
            }
            actual_best = min(methods, key=lambda m: abs(methods[m] - ideal))
            assert entry["best_method"] == actual_best, (
                f"best_method for '{cid}' should be '{actual_best}', "
                f"got '{entry['best_method']}'"
            )


# ===== Anti-cheat: Novel 1-qubit circuit =====


class TestNovelCircuit:
    """Verify the pipeline generalizes to an unseen T/Tdg identity circuit."""

    NOVEL_CIRCUIT_PATH = os.path.join(CIRCUITS_DIR, "identity_t24.json")
    NOVEL_CIRCUIT = {
        "id": "identity_t24",
        "n_qubits": 1,
        "gates": [
            {"name": g, "targets": [0]}
            for _ in range(12)
            for g in ("T", "Tdg")
        ],
        "observable": [[1, 0], [0, 0]],
    }

    @pytest.fixture(autouse=True, scope="class")
    def setup_and_run(self):
        with open(self.NOVEL_CIRCUIT_PATH, "w") as f:
            json.dump(self.NOVEL_CIRCUIT, f)
        result = subprocess.run(
            [sys.executable, BENCHMARK_SCRIPT],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Benchmark failed with novel circuit:\n{result.stderr}"
        )
        yield
        if os.path.exists(self.NOVEL_CIRCUIT_PATH):
            os.remove(self.NOVEL_CIRCUIT_PATH)

    def _load_results(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    def test_novel_circuit_in_results(self):
        results = self._load_results()
        assert "identity_t24" in results, "Novel circuit missing from results"

    def test_novel_ideal_value(self):
        results = self._load_results()
        assert abs(results["identity_t24"]["ideal"] - 1.0) < 1e-9

    def test_novel_unmitigated_degraded(self):
        results = self._load_results()
        assert results["identity_t24"]["unmitigated"] < 1.0

    def test_novel_noisy_decrease(self):
        results = self._load_results()
        nv = results["identity_t24"]["noisy_values"]
        assert nv[0] > nv[1] > nv[2], f"Non-monotonic: {nv}"

    def test_novel_all_methods_improve(self):
        results = self._load_results()
        entry = results["identity_t24"]
        ideal = entry["ideal"]
        unmit_err = abs(entry["unmitigated"] - ideal)
        for method in ["richardson", "polynomial_2", "exponential"]:
            method_err = abs(entry[method] - ideal)
            assert method_err < unmit_err, (
                f"'{method}' did not improve for novel circuit: "
                f"method_err={method_err:.6f}, unmit_err={unmit_err:.6f}"
            )

    def test_novel_exponential_accuracy(self):
        """Exponential should be accurate for this 1-qubit circuit."""
        results = self._load_results()
        assert abs(results["identity_t24"]["exponential"] - 1.0) < 0.05

    def test_novel_best_method_correct(self):
        results = self._load_results()
        entry = results["identity_t24"]
        ideal = entry["ideal"]
        methods = {
            "richardson": entry["richardson"],
            "polynomial_2": entry["polynomial_2"],
            "exponential": entry["exponential"],
        }
        actual_best = min(methods, key=lambda m: abs(methods[m] - ideal))
        assert entry["best_method"] == actual_best

    def test_novel_unmitigated_matches_simulator(self):
        """Verify the novel circuit unmitigated matches direct simulation."""
        results = self._load_results()
        circuit = load_circuit(self.NOVEL_CIRCUIT_PATH)
        expected = simulate(circuit, noise_level=0.01)
        assert abs(results["identity_t24"]["unmitigated"] - expected) < 1e-9


# ===== Anti-cheat: Novel 2-qubit circuit =====


class TestNovelTwoQubitCircuit:
    """Verify generalization to an unseen 2-qubit identity circuit."""

    NOVEL_PATH = os.path.join(CIRCUITS_DIR, "identity_hcnot16.json")

    @pytest.fixture(autouse=True, scope="class")
    def setup_and_run(self):
        # (H x I)(CNOT)(CNOT)(H x I) = I x I, repeated 4 times
        block = [
            {"name": "H", "targets": [0]},
            {"name": "CNOT", "targets": [0, 1]},
            {"name": "CNOT", "targets": [0, 1]},
            {"name": "H", "targets": [0]},
        ]
        circuit = {
            "id": "identity_hcnot16",
            "n_qubits": 2,
            "gates": block * 4,
            "observable": [
                [1, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ],
        }
        with open(self.NOVEL_PATH, "w") as f:
            json.dump(circuit, f)
        result = subprocess.run(
            [sys.executable, BENCHMARK_SCRIPT],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Benchmark failed with 2-qubit novel circuit:\n{result.stderr}"
        )
        yield
        if os.path.exists(self.NOVEL_PATH):
            os.remove(self.NOVEL_PATH)

    def _load_results(self):
        with open(RESULTS_PATH) as f:
            return json.load(f)

    def test_2q_novel_in_results(self):
        results = self._load_results()
        assert "identity_hcnot16" in results

    def test_2q_ideal(self):
        results = self._load_results()
        assert abs(results["identity_hcnot16"]["ideal"] - 1.0) < 1e-9

    def test_2q_unmitigated_degraded(self):
        results = self._load_results()
        assert results["identity_hcnot16"]["unmitigated"] < 1.0

    def test_2q_noisy_decrease(self):
        results = self._load_results()
        nv = results["identity_hcnot16"]["noisy_values"]
        assert nv[0] > nv[1] > nv[2], f"Non-monotonic: {nv}"

    def test_2q_improvement(self):
        """At least one method must improve over unmitigated."""
        results = self._load_results()
        entry = results["identity_hcnot16"]
        ideal = entry["ideal"]
        unmit_err = abs(entry["unmitigated"] - ideal)
        best_err = min(
            abs(entry[m] - ideal)
            for m in ["richardson", "polynomial_2", "exponential"]
        )
        assert best_err < unmit_err, (
            f"No method improved for novel 2-qubit circuit: "
            f"unmit_err={unmit_err:.6f}, best_err={best_err:.6f}"
        )

    def test_2q_best_method_correct(self):
        results = self._load_results()
        entry = results["identity_hcnot16"]
        ideal = entry["ideal"]
        methods = {
            "richardson": entry["richardson"],
            "polynomial_2": entry["polynomial_2"],
            "exponential": entry["exponential"],
        }
        actual_best = min(methods, key=lambda m: abs(methods[m] - ideal))
        assert entry["best_method"] == actual_best

    def test_2q_unmitigated_matches_simulator(self):
        results = self._load_results()
        circuit = load_circuit(self.NOVEL_PATH)
        expected = simulate(circuit, noise_level=0.01)
        assert abs(results["identity_hcnot16"]["unmitigated"] - expected) < 1e-9
