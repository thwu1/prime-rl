
import json
import os
import re
import glob
import numpy as np
import pytest


SYSTEM_NAMES = ["hubbard_2site", "hubbard_3site"]

# ====================================================================
# Pre-computed reference DNA values (openfermion-verified ground truth)
# These are specific to the task's non-standard Hubbard parameters:
#   2-site: t=0.85, U=2.3, nuc_rep=0.37
#   3-site: t=1.0,  U=3.7, nuc_rep=0.0
# ====================================================================

DNA_REF = {
    "hubbard_2site": {
        "ground_state_energy": -0.5324375751773791,
        "n_qubits": 4,
        "jw_num_terms": 11,
        "bk_num_terms": 11,
        "max_eigenvalue": 4.970000000000001,
        "eigenvalue_sum": 24.32,
        "eigenvalue_sum_sq": 80.2664,
        "n_eigenvalues": 16,
        "eigenvalues_sorted": [
            -0.5324375751773791, -0.48, -0.48, 0.37, 0.37,
            0.37, 0.37, 1.22, 1.22, 1.82, 1.82, 2.67,
            3.52, 3.52, 3.572437575177379, 4.97,
        ],
    },
    "hubbard_3site": {
        "ground_state_energy": -2.0314043904878227,
        "n_qubits": 6,
        "jw_num_terms": 18,
        "bk_num_terms": 18,
        "max_eigenvalue": 11.1,
        "eigenvalue_sum": 177.6,
        "eigenvalue_sum_sq": 1113.68,
        "n_eigenvalues": 64,
        "eigenvalues_sorted": [
            -2.0314043904878227, -1.4142135623730956, -1.4142135623730956,
            -1.4142135623730956, -1.414213562373095, -1.4142135623730927,
            -1.3033291573978856, -1.303329157397885, -0.4786262044390047,
            -0.47862620443900084, -0.4786262044389995,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.7280752330899404,
            1.414213562373094, 1.4142135623730945, 1.4142135623730947,
            1.414213562373095, 1.414213562373095,
            1.668595609512179,
            2.2857864376269035, 2.2857864376269035, 2.285786437626905,
            2.2857864376269057, 2.285786437626906,
            2.9719247669100533, 2.971924766910059,
            3.221373795560999,
            3.7, 3.7, 3.7, 3.7, 3.7, 3.7,
            4.178626204439007, 4.178626204439007, 4.1786262044390075,
            4.4280752330899436,
            5.003329157397881,
            5.114213562373094, 5.114213562373094, 5.114213562373095,
            5.114213562373096, 5.114213562373099,
            5.731404390487823, 5.731404390487824,
            5.985786437626903, 5.985786437626906,
            7.4, 7.4, 7.4,
            7.878626204439,
            8.703329157397878,
            8.814213562373094, 8.814213562373098,
            11.1,
        ],
    },
}


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


# === Result file existence ===


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found at /app/"

    def test_all_systems_present(self, results):
        for name in SYSTEM_NAMES:
            assert name in results, f"System '{name}' missing from results.json"


# === No openfermion in agent code ===


class TestNoOpenfermion:
    def test_agent_code_does_not_import_openfermion(self):
        """Verify the agent implemented transformations from scratch."""
        py_files = glob.glob("/app/*.py") + glob.glob("/app/src/*.py")
        for fpath in py_files:
            with open(fpath) as f:
                content = f.read()
            assert "openfermion" not in content.lower(), (
                f"{fpath} imports or references openfermion. "
                "The task requires implementing transformations from scratch."
            )


# === Makefile structure ===


class TestMakefile:
    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "Makefile not found at /app/"

    def test_all_target_includes_audit_run_summary(self):
        with open("/app/Makefile") as f:
            content = f.read()
        all_match = re.search(r"^all\s*:(.+)$", content, re.MULTILINE)
        assert all_match, "'all' target not found in Makefile"
        deps = all_match.group(1)
        assert "audit" in deps, "'all' target missing 'audit' dependency"
        assert "run" in deps, "'all' target missing 'run' dependency"
        assert "summary" in deps, "'all' target missing 'summary' dependency"

    def test_makefile_audit_uses_sqlite3(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "sqlite3" in content, "Makefile should use sqlite3 CLI for audit target"

    def test_makefile_summary_uses_jq(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "jq" in content, "Makefile should use jq for summary target"


# === Database audit output ===


class TestDbAudit:
    def test_audit_file_exists(self):
        assert os.path.isfile("/app/db_audit.txt"), "db_audit.txt not found at /app/"

    def test_audit_contains_schema(self):
        with open("/app/db_audit.txt") as f:
            content = f.read()
        assert "CREATE TABLE" in content, "Audit should contain CREATE TABLE statements"
        assert "molecular_systems" in content, "Audit should mention molecular_systems table"
        assert "one_body" in content, "Audit should mention one_body table"
        assert "two_body" in content, "Audit should mention two_body table"

    def test_audit_contains_row_counts(self):
        with open("/app/db_audit.txt") as f:
            content = f.read()
        lower = content.lower()
        assert "row count" in lower or "Row Counts" in content, (
            "Audit should contain row count information"
        )

    def test_audit_lists_systems(self):
        with open("/app/db_audit.txt") as f:
            content = f.read()
        for name in SYSTEM_NAMES:
            assert name in content, f"Audit should list system '{name}'"


# === Summary output ===


class TestSummary:
    def test_summary_file_exists(self):
        assert os.path.isfile("/app/summary.json"), "summary.json not found at /app/"

    def test_summary_has_required_keys(self, results):
        with open("/app/summary.json") as f:
            summary = json.load(f)
        for name in SYSTEM_NAMES:
            assert f"{name}_energy" in summary, (
                f"summary.json missing '{name}_energy'"
            )
            assert f"{name}_spectral_match" in summary, (
                f"summary.json missing '{name}_spectral_match'"
            )

    def test_summary_values_match_results(self, results):
        with open("/app/summary.json") as f:
            summary = json.load(f)
        for name in SYSTEM_NAMES:
            assert abs(summary[f"{name}_energy"] - results[name]["ground_state_energy"]) < 1e-10, (
                f"summary.json '{name}_energy' doesn't match results.json"
            )
            assert summary[f"{name}_spectral_match"] == results[name]["spectral_match"], (
                f"summary.json '{name}_spectral_match' doesn't match results.json"
            )


# === Ground state energy (DNA check) ===


@pytest.mark.parametrize("system_name", SYSTEM_NAMES)
class TestGroundStateEnergy:
    def test_ground_state_energy(self, results, system_name):
        res = results[system_name]
        ref_energy = DNA_REF[system_name]["ground_state_energy"]
        assert abs(res["ground_state_energy"] - ref_energy) < 1e-6, (
            f"[{system_name}] Ground state energy mismatch: "
            f"got {res['ground_state_energy']}, expected {ref_energy}"
        )


# === Qubit count (DNA check) ===


@pytest.mark.parametrize("system_name", SYSTEM_NAMES)
class TestQubitCount:
    def test_n_qubits(self, results, system_name):
        res = results[system_name]
        ref_nq = DNA_REF[system_name]["n_qubits"]
        assert res["n_qubits"] == ref_nq, (
            f"[{system_name}] n_qubits mismatch: got {res['n_qubits']}, expected {ref_nq}"
        )


# === Term counts (DNA check) ===


@pytest.mark.parametrize("system_name", SYSTEM_NAMES)
class TestTermCounts:
    def test_encoding_term_counts(self, results, system_name):
        """Check that the two encoding term counts match JW and BK (in either order)."""
        res = results[system_name]
        ref = DNA_REF[system_name]
        agent_set = sorted([res["encoding_a_num_terms"], res["encoding_b_num_terms"]])
        ref_set = sorted([ref["jw_num_terms"], ref["bk_num_terms"]])
        assert agent_set == ref_set, (
            f"[{system_name}] Encoding term count set mismatch: "
            f"got {agent_set}, expected {ref_set}"
        )


# === Eigenvalues (DNA check) ===


@pytest.mark.parametrize("system_name", SYSTEM_NAMES)
class TestEigenvalues:
    def test_eigenvalue_count(self, results, system_name):
        res = results[system_name]
        ref_count = DNA_REF[system_name]["n_eigenvalues"]
        assert len(res["eigenvalues_sorted"]) == ref_count, (
            f"[{system_name}] Eigenvalue count mismatch: "
            f"got {len(res['eigenvalues_sorted'])}, expected {ref_count}"
        )

    def test_eigenvalue_values(self, results, system_name):
        res = results[system_name]
        ref_eigs = np.array(DNA_REF[system_name]["eigenvalues_sorted"])
        agent_eigs = np.array(res["eigenvalues_sorted"])
        assert np.allclose(agent_eigs, ref_eigs, atol=1e-6), (
            f"[{system_name}] Eigenvalue mismatch.\n"
            f"First 5 agent: {agent_eigs[:5]}\n"
            f"First 5 reference: {ref_eigs[:5]}"
        )

    def test_eigenvalue_sum(self, results, system_name):
        """Cross-check via trace (sum of eigenvalues)."""
        agent_eigs = np.array(results[system_name]["eigenvalues_sorted"])
        ref_sum = DNA_REF[system_name]["eigenvalue_sum"]
        assert abs(np.sum(agent_eigs) - ref_sum) < 0.1, (
            f"[{system_name}] Eigenvalue sum mismatch: "
            f"got {np.sum(agent_eigs):.4f}, expected {ref_sum:.4f}"
        )

    def test_max_eigenvalue(self, results, system_name):
        agent_eigs = np.array(results[system_name]["eigenvalues_sorted"])
        ref_max = DNA_REF[system_name]["max_eigenvalue"]
        assert abs(agent_eigs[-1] - ref_max) < 1e-6, (
            f"[{system_name}] Max eigenvalue mismatch: "
            f"got {agent_eigs[-1]}, expected {ref_max}"
        )


# === Spectral match ===


@pytest.mark.parametrize("system_name", SYSTEM_NAMES)
class TestSpectralMatch:
    def test_spectral_match_flag(self, results, system_name):
        res = results[system_name]
        assert res["spectral_match"] is True, (
            f"[{system_name}] Both encodings should yield identical spectra "
            f"(spectral_match should be true)"
        )


# === Symmetry reduction ===


@pytest.mark.parametrize("system_name", SYSTEM_NAMES)
class TestSymmetryReduction:
    def test_symmetries_found(self, results, system_name):
        res = results[system_name]
        assert res["n_symmetries"] >= 1, (
            f"[{system_name}] Should find at least 1 symmetry"
        )

    def test_tapered_qubits_reduced(self, results, system_name):
        res = results[system_name]
        assert res["tapered_n_qubits"] < res["n_qubits"], (
            f"[{system_name}] Tapered qubit count ({res['tapered_n_qubits']}) "
            f"should be less than original ({res['n_qubits']})"
        )

    def test_tapered_qubit_count_consistent(self, results, system_name):
        res = results[system_name]
        expected = res["n_qubits"] - res["n_symmetries"]
        assert res["tapered_n_qubits"] == expected, (
            f"[{system_name}] tapered_n_qubits ({res['tapered_n_qubits']}) "
            f"should equal n_qubits - n_symmetries ({expected})"
        )

    def test_tapered_ground_state_energy(self, results, system_name):
        res = results[system_name]
        ref_energy = DNA_REF[system_name]["ground_state_energy"]
        assert abs(res["tapered_ground_state_energy"] - ref_energy) < 1e-6, (
            f"[{system_name}] Tapered ground state energy "
            f"({res['tapered_ground_state_energy']}) should match "
            f"full ground state energy ({ref_energy})"
        )
