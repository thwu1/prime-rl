
import sys
import json
import os
import re
import sqlite3

import numpy as np
import pytest

sys.path.insert(0, "/app")

EDGE_IDS = ["E1", "E2", "E3", "E4", "E5"]


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture
def network():
    with open("/app/network.json") as f:
        return json.load(f)


# ── Result format and correctness ──────────────────────────────────────


class TestResultsFormat:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_all_edges_present(self, results):
        for eid in EDGE_IDS:
            assert eid in results, f"Missing edge {eid}"

    def test_required_fields(self, results):
        for eid, r in results.items():
            for field in ("fidelity", "success_probability", "num_pairs",
                          "exceeds_threshold"):
                assert field in r, f"{eid} missing field '{field}'"


class TestThresholds:
    def test_all_exceed_thresholds(self, results, network):
        thresholds = {e["id"]: e["threshold"] for e in network["edges"]}
        for eid, r in results.items():
            assert r["fidelity"] > thresholds[eid], (
                f"{eid}: fidelity {r['fidelity']:.6f} <= "
                f"threshold {thresholds[eid]}"
            )

    def test_exceeds_threshold_flag(self, results):
        for eid, r in results.items():
            assert r["exceeds_threshold"] is True, (
                f"{eid}: exceeds_threshold should be True"
            )


class TestAnalyticalValues:
    """Check known analytical results for simple noise models."""

    def test_e1_fidelity(self, results):
        assert abs(results["E1"]["fidelity"] - 0.9) < 0.005

    def test_e1_success_prob(self, results):
        assert abs(results["E1"]["success_probability"] - 0.625) < 0.005

    def test_e2_fidelity(self, results):
        assert abs(results["E2"]["fidelity"] - 0.9) < 0.005

    def test_e2_success_prob(self, results):
        assert abs(results["E2"]["success_probability"] - 0.625) < 0.005


class TestConstraints:
    def test_success_probability_range(self, results):
        for eid, r in results.items():
            assert 0 < r["success_probability"] <= 1.0, (
                f"{eid}: invalid success_probability {r['success_probability']}"
            )

    def test_num_pairs_within_limits(self, results, network):
        max_p = {e["id"]: e["max_pairs"] for e in network["edges"]}
        for eid, r in results.items():
            assert r["num_pairs"] <= max_p[eid], (
                f"{eid}: used {r['num_pairs']} pairs, max {max_p[eid]}"
            )

    def test_fidelity_physical_range(self, results):
        for eid, r in results.items():
            assert 0.0 <= r["fidelity"] <= 1.0, (
                f"{eid}: fidelity {r['fidelity']} out of [0,1]"
            )


# ── Simulator unit tests ──────────────────────────────────────────────


class TestSimulatorInit:
    def test_perfect_pair(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(1, 0.0, 0.0)
        assert rho.shape == (4, 4)
        f = compute_fidelity(rho, 0, 1, 2)
        assert abs(f - 1.0) < 1e-10

    def test_noisy_bit_flip(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(1, 0.25, 0.0)
        f = compute_fidelity(rho, 0, 1, 2)
        assert abs(f - 0.75) < 1e-10

    def test_noisy_phase_flip(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(1, 0.0, 0.25)
        f = compute_fidelity(rho, 0, 1, 2)
        assert abs(f - 0.75) < 1e-10

    def test_noisy_mixed(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(1, 0.30, 0.10)
        f = compute_fidelity(rho, 0, 1, 2)
        expected = (1 - 0.30) * (1 - 0.10)
        assert abs(f - expected) < 1e-10

    def test_valid_density_matrix_single(self):
        from simulator import initialize_pairs

        rho = initialize_pairs(1, 0.25, 0.15)
        assert abs(np.trace(rho) - 1.0) < 1e-10
        assert np.allclose(rho, rho.conj().T, atol=1e-12)
        eigvals = np.linalg.eigvalsh(rho)
        assert all(ev >= -1e-10 for ev in eigvals)

    def test_valid_density_matrix_multi(self):
        from simulator import initialize_pairs

        rho = initialize_pairs(2, 0.20, 0.10)
        assert rho.shape == (16, 16)
        assert abs(np.trace(rho) - 1.0) < 1e-10
        assert np.allclose(rho, rho.conj().T, atol=1e-12)
        eigvals = np.linalg.eigvalsh(rho)
        assert all(ev >= -1e-10 for ev in eigvals)

    def test_two_pair_output_fidelity(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(2, 0.0, 0.0)
        f = compute_fidelity(rho, 1, 2, 4)
        assert abs(f - 1.0) < 1e-10

    def test_two_pair_noisy_output_fidelity(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(2, 0.25, 0.0)
        f = compute_fidelity(rho, 1, 2, 4)
        assert abs(f - 0.75) < 1e-10

    def test_two_pair_noisy_ancilla_fidelity(self):
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(2, 0.25, 0.0)
        f = compute_fidelity(rho, 0, 3, 4)
        assert abs(f - 0.75) < 1e-10

    def test_generalization_unseen_params(self):
        """Simulator works on noise params not in network.json."""
        from simulator import initialize_pairs, compute_fidelity

        rho = initialize_pairs(1, 0.40, 0.05)
        f = compute_fidelity(rho, 0, 1, 2)
        expected = (1 - 0.40) * (1 - 0.05)
        assert abs(f - expected) < 1e-10


class TestLOCC:
    def test_alice_side_valid(self):
        from simulator import check_locc

        valid, _ = check_locc([("cx", [0, 1])], 2)
        assert valid

    def test_bob_side_valid(self):
        from simulator import check_locc

        valid, _ = check_locc([("cx", [2, 3])], 2)
        assert valid

    def test_cross_boundary_invalid(self):
        from simulator import check_locc

        valid, _ = check_locc([("cx", [1, 2])], 2)
        assert not valid

    def test_single_qubit_always_valid(self):
        from simulator import check_locc

        valid, _ = check_locc([("h", [0]), ("h", [3])], 2)
        assert valid

    def test_multiple_gates_all_valid(self):
        from simulator import check_locc

        gates = [("cx", [1, 0]), ("cx", [2, 3]), ("h", [1]), ("h", [2])]
        valid, _ = check_locc(gates, 2)
        assert valid

    def test_multiple_gates_one_invalid(self):
        from simulator import check_locc

        gates = [("cx", [1, 0]), ("cx", [0, 2])]
        valid, _ = check_locc(gates, 2)
        assert not valid

    def test_three_pair_valid(self):
        from simulator import check_locc

        gates = [("cx", [2, 0]), ("cx", [3, 5]),
                 ("cx", [2, 1]), ("cx", [3, 4])]
        valid, _ = check_locc(gates, 3)
        assert valid

    def test_three_pair_invalid(self):
        from simulator import check_locc

        gates = [("cx", [2, 3])]
        valid, _ = check_locc(gates, 3)
        assert not valid


# ── OpenQASM 3.0 circuit file tests ─────────────────────────────────


class TestQASMCircuits:
    def test_circuits_directory_exists(self):
        assert os.path.isdir("/app/circuits"), "/app/circuits/ directory not found"

    def test_all_edges_have_qasm(self):
        for eid in EDGE_IDS:
            path = f"/app/circuits/{eid}.qasm"
            assert os.path.isfile(path), f"Missing circuit file {eid}.qasm"

    def test_qasm_header(self):
        for eid in EDGE_IDS:
            with open(f"/app/circuits/{eid}.qasm") as f:
                content = f.read()
            assert re.search(r"OPENQASM\s+3", content), (
                f"{eid}.qasm missing OPENQASM 3.0 header"
            )

    def test_qasm_has_qubit_declaration(self):
        for eid in EDGE_IDS:
            with open(f"/app/circuits/{eid}.qasm") as f:
                content = f.read()
            assert re.search(r"qubit\s*\[", content), (
                f"{eid}.qasm missing qubit declaration"
            )

    def test_qasm_has_measurement(self):
        for eid in EDGE_IDS:
            with open(f"/app/circuits/{eid}.qasm") as f:
                content = f.read()
            assert "measure" in content.lower(), (
                f"{eid}.qasm missing measurement operations"
            )

    def test_qasm_qubit_count_matches_results(self, results):
        for eid in EDGE_IDS:
            with open(f"/app/circuits/{eid}.qasm") as f:
                content = f.read()
            match = re.search(r"qubit\s*\[(\d+)\]", content)
            assert match, f"{eid}.qasm: cannot parse qubit declaration"
            n_qubits = int(match.group(1))
            expected = 2 * results[eid]["num_pairs"]
            assert n_qubits == expected, (
                f"{eid}: QASM declares {n_qubits} qubits, expected {expected} "
                f"(2 * {results[eid]['num_pairs']} pairs)"
            )

    def test_qasm_locc_compliance(self):
        """Parse QASM files and verify two-qubit gates respect LOCC."""
        two_qubit_gates = {"cx", "cz", "swap", "cnot"}

        for eid in EDGE_IDS:
            with open(f"/app/circuits/{eid}.qasm") as f:
                content = f.read()

            match = re.search(r"qubit\s*\[(\d+)\]", content)
            assert match, f"{eid}.qasm: no qubit declaration"
            n_qubits = int(match.group(1))
            n_pairs = n_qubits // 2
            alice = set(range(n_pairs))

            gate_pattern = re.compile(
                r"(\w+)\s+q\[(\d+)\]\s*,\s*q\[(\d+)\]"
            )
            for m in gate_pattern.finditer(content):
                gname = m.group(1).lower()
                if gname in two_qubit_gates:
                    q1, q2 = int(m.group(2)), int(m.group(3))
                    both_alice = q1 in alice and q2 in alice
                    both_bob = q1 not in alice and q2 not in alice
                    assert both_alice or both_bob, (
                        f"{eid}: gate {gname} q[{q1}],q[{q2}] violates LOCC "
                        f"(N={n_pairs}, Alice=0..{n_pairs-1})"
                    )

    def test_qasm_nonempty_circuit(self):
        """Each QASM file must have at least one gate operation."""
        gate_pattern = re.compile(
            r"^\s*(cx|h|x|z|cz|swap|cnot)\s+q\[",
            re.MULTILINE | re.IGNORECASE,
        )
        for eid in EDGE_IDS:
            with open(f"/app/circuits/{eid}.qasm") as f:
                content = f.read()
            assert gate_pattern.search(content), (
                f"{eid}.qasm contains no gate operations"
            )


# ── SQLite database tests ───────────────────────────────────────────


class TestSQLiteResults:
    def test_database_exists(self):
        assert os.path.isfile("/app/results.db"), "results.db not found"

    def test_results_table_exists(self):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='results'"
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None, "'results' table not found in database"

    def test_db_schema_columns(self):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(results)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        for col in ("edge_id", "fidelity", "success_probability",
                     "num_pairs", "exceeds_threshold"):
            assert col in cols, f"Column '{col}' missing from results table"

    def test_all_edges_in_db(self):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("SELECT edge_id FROM results ORDER BY edge_id")
        ids = [row[0] for row in cur.fetchall()]
        conn.close()
        for eid in EDGE_IDS:
            assert eid in ids, f"Missing edge {eid} in database"

    def test_db_fidelities_exceed_thresholds(self, network):
        thresholds = {e["id"]: e["threshold"] for e in network["edges"]}
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        for eid, thresh in thresholds.items():
            cur.execute(
                "SELECT fidelity FROM results WHERE edge_id=?", (eid,)
            )
            row = cur.fetchone()
            assert row is not None, f"Missing {eid} in database"
            assert row[0] > thresh, (
                f"{eid}: DB fidelity {row[0]:.6f} <= threshold {thresh}"
            )
        conn.close()

    def test_db_matches_json(self, results):
        """SQLite and JSON results must be consistent."""
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        for eid in EDGE_IDS:
            cur.execute(
                "SELECT fidelity, success_probability, num_pairs, "
                "exceeds_threshold FROM results WHERE edge_id=?",
                (eid,),
            )
            row = cur.fetchone()
            assert row is not None, f"Missing {eid} in database"
            assert abs(row[0] - results[eid]["fidelity"]) < 1e-6, (
                f"{eid}: DB fidelity {row[0]} != JSON {results[eid]['fidelity']}"
            )
            assert abs(row[1] - results[eid]["success_probability"]) < 1e-6, (
                f"{eid}: DB success_prob {row[1]} != JSON "
                f"{results[eid]['success_probability']}"
            )
            assert row[2] == results[eid]["num_pairs"], (
                f"{eid}: DB num_pairs {row[2]} != JSON "
                f"{results[eid]['num_pairs']}"
            )
            json_flag = 1 if results[eid]["exceeds_threshold"] else 0
            assert row[3] == json_flag, (
                f"{eid}: DB exceeds_threshold {row[3]} != JSON {json_flag}"
            )
        conn.close()

    def test_db_queryable_via_sql(self):
        """Verify the database supports meaningful aggregate queries."""
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM results WHERE exceeds_threshold=1")
        count = cur.fetchone()[0]
        conn.close()
        assert count == 5, (
            f"Expected 5 edges exceeding threshold, got {count}"
        )
