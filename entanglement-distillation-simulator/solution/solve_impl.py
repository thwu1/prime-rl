#!/usr/bin/env python3
"""
Solution for quantum entanglement distillation task.

Writes OpenQASM 3.0 circuit files, validates LOCC compliance,
runs density-matrix simulation, and outputs results.

"""
import os
import json
import subprocess
import numpy as np


# ============================================================
# OpenQASM 3.0 Circuit Definitions
# ============================================================

QASM_CIRCUITS = {
    # S1: Bit-flip noise, F=0.80, N=2
    # Bilateral parity check on 4 qubits (Alice: 0,1; Bob: 2,3)
    # Pairs: (0,3)=ancilla, (1,2)=output
    "S1": """\
OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
bit[2] c;
cx q[1], q[0];
cx q[2], q[3];
c[0] = measure q[0];
c[1] = measure q[3];
""",
    # S2: Phase-flip noise, F=0.80, N=2
    # Hadamard converts phase-flip to bit-flip, same parity check
    "S2": """\
OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
bit[2] c;
h q[0];
h q[1];
h q[2];
h q[3];
cx q[1], q[0];
cx q[2], q[3];
h q[1];
h q[2];
c[0] = measure q[0];
c[1] = measure q[3];
""",
    # S3: Bit-flip noise, F=0.75, N=3
    # Two bilateral parity checks on 6 qubits (Alice: 0,1,2; Bob: 3,4,5)
    # Pairs: (0,5)=anc0, (1,4)=anc1, (2,3)=output
    "S3": """\
OPENQASM 3.0;
include "stdgates.inc";
qubit[6] q;
bit[4] c;
cx q[2], q[0];
cx q[3], q[5];
cx q[2], q[1];
cx q[3], q[4];
c[0] = measure q[0];
c[1] = measure q[1];
c[2] = measure q[4];
c[3] = measure q[5];
""",
    # S4: Phase-flip noise, F=0.75, N=3
    "S4": """\
OPENQASM 3.0;
include "stdgates.inc";
qubit[6] q;
bit[4] c;
h q[0];
h q[1];
h q[2];
h q[3];
h q[4];
h q[5];
cx q[2], q[0];
cx q[3], q[5];
cx q[2], q[1];
cx q[3], q[4];
h q[2];
h q[3];
c[0] = measure q[0];
c[1] = measure q[1];
c[2] = measure q[4];
c[3] = measure q[5];
""",
    # S5: Heavy bit-flip noise, F=0.70, N=5
    # Four bilateral parity checks on 10 qubits
    # Alice: 0-4, Bob: 5-9. Output pair: (4,5)
    "S5": """\
OPENQASM 3.0;
include "stdgates.inc";
qubit[10] q;
bit[8] c;
cx q[4], q[3];
cx q[5], q[6];
cx q[4], q[2];
cx q[5], q[7];
cx q[4], q[1];
cx q[5], q[8];
cx q[4], q[0];
cx q[5], q[9];
c[0] = measure q[0];
c[1] = measure q[1];
c[2] = measure q[2];
c[3] = measure q[3];
c[4] = measure q[6];
c[5] = measure q[7];
c[6] = measure q[8];
c[7] = measure q[9];
""",
}

N_VALUES = {"S1": 2, "S2": 2, "S3": 3, "S4": 3, "S5": 5}


# ============================================================
# Bell state definitions
# ============================================================

PHI_P = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
PHI_M = np.array([1, 0, 0, -1], dtype=complex) / np.sqrt(2)
PSI_P = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
PSI_M = np.array([0, 1, -1, 0], dtype=complex) / np.sqrt(2)
H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
I2 = np.eye(2, dtype=complex)


def compute_fidelity_phi_plus(rho):
    """Fidelity of a 2-qubit density matrix w.r.t. |Phi+>."""
    return float(np.real(PHI_P.conj() @ rho @ PHI_P))


def bell_diagonal_dm(coeffs):
    """Build 4x4 density matrix from Bell-diagonal coefficients."""
    rho = np.zeros((4, 4), dtype=complex)
    for p, state in zip(coeffs, [PHI_P, PHI_M, PSI_P, PSI_M]):
        rho += p * np.outer(state, state.conj())
    return rho


# ============================================================
# Density matrix simulation
# ============================================================

def init_n_pairs(single_pair_rho, n):
    """Initialize N Bell pairs with outside-in qubit permutation."""
    total = 2 * n
    rho = single_pair_rho.copy()
    for _ in range(n - 1):
        rho = np.kron(rho, single_pair_rho)

    perm = [0] * total
    for k in range(n):
        perm[2 * k] = k
        perm[2 * k + 1] = 2 * n - 1 - k

    inv_perm = [0] * total
    for i, p in enumerate(perm):
        inv_perm[p] = i

    rho_t = rho.reshape([2] * (2 * total))
    axes = [inv_perm[j] for j in range(total)] + \
           [inv_perm[j] + total for j in range(total)]
    rho_t = rho_t.transpose(axes)
    dim = 2 ** total
    return rho_t.reshape(dim, dim)


def _qubit_bit(basis_idx, qubit, total):
    return (basis_idx >> (total - 1 - qubit)) & 1


def apply_single_gate(rho, gate, qubit, total):
    ops = [I2] * total
    ops[qubit] = gate
    U = ops[0]
    for op in ops[1:]:
        U = np.kron(U, op)
    return U @ rho @ U.conj().T


def apply_cnot(rho, ctrl, targ, total):
    dim = 2 ** total
    perm = np.arange(dim)
    for i in range(dim):
        if _qubit_bit(i, ctrl, total):
            perm[i] = i ^ (1 << (total - 1 - targ))
    U = np.zeros((dim, dim), dtype=complex)
    for i in range(dim):
        U[perm[i], i] = 1.0
    return U @ rho @ U.T


def partial_trace_to_pair(rho, qa, qb, total):
    keep = sorted([qa, qb])
    swap = (qa != keep[0])
    trace_out = [q for q in range(total) if q not in keep]
    n_trace = len(trace_out)
    rho_red = np.zeros((4, 4), dtype=complex)
    for i in range(4):
        ib = [(i >> 1) & 1, i & 1]
        for j in range(4):
            jb = [(j >> 1) & 1, j & 1]
            val = 0.0 + 0j
            for t in range(2 ** n_trace):
                row = 0
                col = 0
                for q in range(total):
                    if q == keep[0]:
                        rb, cb = ib[0], jb[0]
                    elif q == keep[1]:
                        rb, cb = ib[1], jb[1]
                    else:
                        idx = trace_out.index(q)
                        bit = (t >> (n_trace - 1 - idx)) & 1
                        rb, cb = bit, bit
                    shift = total - 1 - q
                    row |= (rb << shift)
                    col |= (cb << shift)
                val += rho[row, col]
            if swap:
                si = (ib[1] << 1) | ib[0]
                sj = (jb[1] << 1) | jb[0]
                rho_red[si, sj] = val
            else:
                rho_red[i, j] = val
    return rho_red


def simulate_protocol(single_pair_rho, n, circuit_fn, flag_fn, output_pair):
    """Simulate a distillation protocol with post-selection."""
    total = 2 * n
    dim = 2 ** total
    rho = init_n_pairs(single_pair_rho, n)
    rho = circuit_fn(rho, total)

    output_set = set(output_pair)
    measured = [q for q in range(total) if q not in output_set]
    n_meas = len(measured)

    qubit_vals = np.zeros((dim, total), dtype=np.int8)
    for b in range(dim):
        for q in range(total):
            qubit_vals[b, q] = _qubit_bit(b, q, total)

    total_p_flag0 = 0.0
    fidelity_accum = 0.0

    for outcome_int in range(2 ** n_meas):
        outcomes = {}
        for idx, q in enumerate(measured):
            outcomes[q] = (outcome_int >> (n_meas - 1 - idx)) & 1

        mask = np.ones(dim, dtype=bool)
        for q, val in outcomes.items():
            mask &= (qubit_vals[:, q] == val)

        mask_f = mask.astype(complex)
        mask_2d = np.outer(mask_f, mask_f)
        rho_proj = rho * mask_2d
        p = np.real(np.trace(rho_proj))

        if p < 1e-15:
            continue
        if flag_fn(outcomes) != 0:
            continue

        total_p_flag0 += p
        rho_norm = rho_proj / p
        rho_out = partial_trace_to_pair(
            rho_norm, output_pair[0], output_pair[1], total)
        f = compute_fidelity_phi_plus(rho_out)
        fidelity_accum += p * f

    if total_p_flag0 < 1e-15:
        return 0.0, 0.0
    return fidelity_accum / total_p_flag0, total_p_flag0


# ============================================================
# Protocol circuit functions and flag functions
# ============================================================

def circuit_d1_n2(rho, total):
    rho = apply_cnot(rho, 1, 0, total)
    rho = apply_cnot(rho, 2, 3, total)
    return rho

def flag_d1_n2(outcomes):
    return outcomes[0] ^ outcomes[3]

def circuit_d2_n2(rho, total):
    for q in range(total):
        rho = apply_single_gate(rho, H_GATE, q, total)
    rho = apply_cnot(rho, 1, 0, total)
    rho = apply_cnot(rho, 2, 3, total)
    rho = apply_single_gate(rho, H_GATE, 1, total)
    rho = apply_single_gate(rho, H_GATE, 2, total)
    return rho

def flag_d2_n2(outcomes):
    return outcomes[0] ^ outcomes[3]

def circuit_d3_n3(rho, total):
    rho = apply_cnot(rho, 2, 0, total)
    rho = apply_cnot(rho, 3, 5, total)
    rho = apply_cnot(rho, 2, 1, total)
    rho = apply_cnot(rho, 3, 4, total)
    return rho

def flag_d3_n3(outcomes):
    s0 = outcomes[0] ^ outcomes[5]
    s1 = outcomes[1] ^ outcomes[4]
    return s0 | s1

def circuit_d4_n3(rho, total):
    for q in range(total):
        rho = apply_single_gate(rho, H_GATE, q, total)
    rho = apply_cnot(rho, 2, 0, total)
    rho = apply_cnot(rho, 3, 5, total)
    rho = apply_cnot(rho, 2, 1, total)
    rho = apply_cnot(rho, 3, 4, total)
    rho = apply_single_gate(rho, H_GATE, 2, total)
    rho = apply_single_gate(rho, H_GATE, 3, total)
    return rho

def flag_d4_n3(outcomes):
    s0 = outcomes[0] ^ outcomes[5]
    s1 = outcomes[1] ^ outcomes[4]
    return s0 | s1

def circuit_d5_n5(rho, total):
    rho = apply_cnot(rho, 4, 3, total)
    rho = apply_cnot(rho, 5, 6, total)
    rho = apply_cnot(rho, 4, 2, total)
    rho = apply_cnot(rho, 5, 7, total)
    rho = apply_cnot(rho, 4, 1, total)
    rho = apply_cnot(rho, 5, 8, total)
    rho = apply_cnot(rho, 4, 0, total)
    rho = apply_cnot(rho, 5, 9, total)
    return rho

def flag_d5_n5(outcomes):
    s0 = outcomes[0] ^ outcomes[9]
    s1 = outcomes[1] ^ outcomes[8]
    s2 = outcomes[2] ^ outcomes[7]
    s3 = outcomes[3] ^ outcomes[6]
    return s0 | s1 | s2 | s3


PROTOCOLS = {
    "S1": (2, circuit_d1_n2, flag_d1_n2, (1, 2)),
    "S2": (2, circuit_d2_n2, flag_d2_n2, (1, 2)),
    "S3": (3, circuit_d3_n3, flag_d3_n3, (2, 3)),
    "S4": (3, circuit_d4_n3, flag_d4_n3, (2, 3)),
    "S5": (5, circuit_d5_n5, flag_d5_n5, (4, 5)),
}


# ============================================================
# QASM file writing and validation
# ============================================================

def write_qasm_files():
    """Write OpenQASM 3.0 circuit files."""
    os.makedirs("/app/circuits", exist_ok=True)
    for scenario, qasm_str in QASM_CIRCUITS.items():
        path = f"/app/circuits/{scenario}.qasm"
        with open(path, "w") as f:
            f.write(qasm_str)
        print(f"  Wrote {path}")


def validate_locc_all():
    """Validate all circuits with the LOCC validator tool."""
    for scenario in ["S1", "S2", "S3", "S4", "S5"]:
        n = N_VALUES[scenario]
        path = f"/app/circuits/{scenario}.qasm"
        result = subprocess.run(
            ["python3", "/app/validate_locc.py", path, str(n)],
            capture_output=True, text=True
        )
        print(f"  {scenario}: {result.stdout.strip()}")
        if result.returncode != 0:
            print(f"  ERROR: LOCC validation failed for {scenario}")
            print(result.stderr)


# ============================================================
# Scenario simulation
# ============================================================

def run_scenario(scenario_id, bell_diag, threshold):
    """Run the optimal protocol for a scenario."""
    rho_single = bell_diagonal_dm(bell_diag)
    n, circuit_fn, flag_fn, output_pair = PROTOCOLS[scenario_id]

    print(f"  Simulating N={n}, output pair={output_pair}...")
    fidelity, success_prob = simulate_protocol(
        rho_single, n, circuit_fn, flag_fn, output_pair)

    cs = fidelity * success_prob
    return {
        "fidelity": round(float(fidelity), 10),
        "success_probability": round(float(success_prob), 10),
        "claim_strength": round(float(cs), 10),
        "num_bell_pairs": n,
        "meets_threshold": bool(fidelity >= threshold - 1e-9),
    }


def write_simulator_module():
    """Write /app/simulator.py with required API."""
    code = '''\
"""Quantum entanglement distillation fidelity computation module."""
import numpy as np

PHI_PLUS = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)


def compute_fidelity_phi_plus(rho):
    """Compute fidelity of a 2-qubit density matrix w.r.t. |Phi+>.

    Args:
        rho: 4x4 complex numpy array (2-qubit density matrix)

    Returns:
        float: fidelity F = <Phi+|rho|Phi+>
    """
    return float(np.real(PHI_PLUS.conj() @ rho @ PHI_PLUS))
'''
    with open("/app/simulator.py", "w") as f:
        f.write(code)


# ============================================================
# Main
# ============================================================

def main():
    print("Step 1: Writing OpenQASM 3.0 circuit files...")
    write_qasm_files()

    print("\nStep 2: Validating LOCC compliance...")
    validate_locc_all()

    print("\nStep 3: Loading scenarios...")
    with open("/app/scenarios.json") as f:
        scenarios = json.load(f)

    print("\nStep 4: Simulating distillation protocols...")
    results = {}
    for sid in ["S1", "S2", "S3", "S4", "S5"]:
        sc = scenarios[sid]
        print(f"\n  {sid}: {sc['description']}")
        result = run_scenario(sid, sc["bell_diagonal"], sc["threshold"])
        results[sid] = result
        print(f"    F={result['fidelity']:.6f}, p={result['success_probability']:.6f}, "
              f"cs={result['claim_strength']:.6f}, meets={result['meets_threshold']}")

    print("\nStep 5: Writing results...")
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("  Wrote /app/results.json")

    write_simulator_module()
    print("  Wrote /app/simulator.py")

    print("\nDone.")


if __name__ == "__main__":
    main()
