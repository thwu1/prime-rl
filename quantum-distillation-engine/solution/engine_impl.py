"""
Entanglement Distillation Simulation Engine - Full Implementation

"""
import numpy as np
import json

# ---- Constants ----
I2 = np.eye(2, dtype=complex)
X_GATE = np.array([[0, 1], [1, 0]], dtype=complex)
Z_GATE = np.array([[1, 0], [0, -1]], dtype=complex)
H_GATE = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
P0 = np.array([[1, 0], [0, 0]], dtype=complex)
P1 = np.array([[0, 0], [0, 1]], dtype=complex)

PHI_PLUS = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
PSI_PLUS = np.array([0, 1, 1, 0], dtype=complex) / np.sqrt(2)
PHI_MINUS = np.array([1, 0, 0, -1], dtype=complex) / np.sqrt(2)
PSI_MINUS = np.array([0, 1, -1, 0], dtype=complex) / np.sqrt(2)


# ---- Helper: Kronecker chain ----

def _kron_chain(ops):
    result = ops[0]
    for op in ops[1:]:
        result = np.kron(result, op)
    return result


def _gate_on_qubit(gate, qubit, n_qubits):
    ops = [I2] * n_qubits
    ops[qubit] = gate
    return _kron_chain(ops)


# ---- Public API ----

def construct_bell_pair_dm(px, pz):
    a = (1 - px) * (1 - pz)
    b = px * (1 - pz)
    c = (1 - px) * pz
    d = px * pz
    return (a * np.outer(PHI_PLUS, PHI_PLUS.conj()) +
            b * np.outer(PSI_PLUS, PSI_PLUS.conj()) +
            c * np.outer(PHI_MINUS, PHI_MINUS.conj()) +
            d * np.outer(PSI_MINUS, PSI_MINUS.conj()))


def construct_n_pairs_dm(n, px, pz):
    single = construct_bell_pair_dm(px, pz)
    nq = 2 * n

    rho_pairs = single
    for _ in range(n - 1):
        rho_pairs = np.kron(rho_pairs, single)

    perm = [0] * nq
    for k in range(n):
        perm[k] = 2 * k
        perm[2 * n - 1 - k] = 2 * k + 1

    return _permute_dm(rho_pairs, perm, nq)


def _permute_dm(rho, perm, nq):
    shape = [2] * (2 * nq)
    t = rho.reshape(shape)
    axes = list(perm) + [p + nq for p in perm]
    t = np.transpose(t, axes)
    return t.reshape(2 ** nq, 2 ** nq)


def validate_locc(gate_targets, n):
    alice = set(range(n))
    bob = set(range(n, 2 * n))
    for targets in gate_targets:
        if len(targets) >= 2:
            qs = set(targets)
            if qs & alice and qs & bob:
                return False
    return True


def compute_fidelity_phi_plus(rho_2q):
    return float(np.real(PHI_PLUS.conj() @ rho_2q @ PHI_PLUS))


def partial_trace(rho, keep_qubits, n_qubits):
    trace_out = sorted(set(range(n_qubits)) - set(keep_qubits))
    nk = len(keep_qubits)
    t = rho.reshape([2] * (2 * n_qubits))
    for q in sorted(trace_out, reverse=True):
        cur_nq = t.ndim // 2
        t = np.trace(t, axis1=q, axis2=q + cur_nq)
    return t.reshape(2 ** nk, 2 ** nk)


# ---- Gate application ----

def _apply_single(rho, gate, qubit, nq):
    U = _gate_on_qubit(gate, qubit, nq)
    return U @ rho @ U.conj().T


def _apply_cnot(rho, ctrl, tgt, nq):
    U = (_gate_on_qubit(P0, ctrl, nq) +
         _gate_on_qubit(P1, ctrl, nq) @ _gate_on_qubit(X_GATE, tgt, nq))
    return U @ rho @ U.conj().T


# ---- Measurement and post-selection ----

def _postselect(rho, meas_qubits, accept_fn, nq):
    nm = len(meas_qubits)
    total_p = 0.0
    rho_acc = np.zeros_like(rho)

    for bits_int in range(2 ** nm):
        bits = [(bits_int >> (nm - 1 - i)) & 1 for i in range(nm)]
        outcome = dict(zip(meas_qubits, bits))
        if not accept_fn(outcome):
            continue

        proj = np.eye(2 ** nq, dtype=complex)
        for q in meas_qubits:
            p_gate = P0 if outcome[q] == 0 else P1
            proj = proj @ _gate_on_qubit(p_gate, q, nq)

        rho_proj = proj @ rho @ proj.conj().T
        p = np.real(np.trace(rho_proj))
        total_p += p
        rho_acc += rho_proj

    if total_p > 1e-15:
        rho_acc /= total_p
    return rho_acc, total_p


# ---- Distillation protocols ----

def _bit_check(rho, out_a, out_b, anc_pairs, nq):
    for anc_a, anc_b in anc_pairs:
        rho = _apply_cnot(rho, out_a, anc_a, nq)
        rho = _apply_cnot(rho, out_b, anc_b, nq)

    meas_qs = []
    for anc_a, anc_b in anc_pairs:
        meas_qs.extend([anc_a, anc_b])

    def accept(o):
        for anc_a, anc_b in anc_pairs:
            if o[anc_a] != o[anc_b]:
                return False
        return True

    return _postselect(rho, meas_qs, accept, nq)


def _phase_check(rho, out_a, out_b, anc_pairs, nq):
    all_qs = [out_a, out_b]
    for a, b in anc_pairs:
        all_qs.extend([a, b])

    for q in all_qs:
        rho = _apply_single(rho, H_GATE, q, nq)

    for anc_a, anc_b in anc_pairs:
        rho = _apply_cnot(rho, out_a, anc_a, nq)
        rho = _apply_cnot(rho, out_b, anc_b, nq)

    meas_qs = []
    for anc_a, anc_b in anc_pairs:
        meas_qs.extend([anc_a, anc_b])

    def accept(o):
        for anc_a, anc_b in anc_pairs:
            if o[anc_a] != o[anc_b]:
                return False
        return True

    rho, prob = _postselect(rho, meas_qs, accept, nq)

    rho = _apply_single(rho, H_GATE, out_a, nq)
    rho = _apply_single(rho, H_GATE, out_b, nq)

    return rho, prob


def _solve_d1():
    n, nq = 2, 4
    rho = construct_n_pairs_dm(n, 0.25, 0.0)
    rho, prob = _bit_check(rho, 1, 2, [(0, 3)], nq)
    rho_out = partial_trace(rho, [1, 2], nq)
    return {"fidelity": compute_fidelity_phi_plus(rho_out),
            "success_probability": prob}


def _solve_d2():
    n, nq = 2, 4
    rho = construct_n_pairs_dm(n, 0.0, 0.25)
    rho, prob = _phase_check(rho, 1, 2, [(0, 3)], nq)
    rho_out = partial_trace(rho, [1, 2], nq)
    return {"fidelity": compute_fidelity_phi_plus(rho_out),
            "success_probability": prob}


def _solve_d3():
    n, nq = 3, 6
    rho = construct_n_pairs_dm(n, 0.25, 0.0)
    rho, prob = _bit_check(rho, 2, 3, [(0, 5), (1, 4)], nq)
    rho_out = partial_trace(rho, [2, 3], nq)
    return {"fidelity": compute_fidelity_phi_plus(rho_out),
            "success_probability": prob}


def _solve_d4():
    n, nq = 3, 6
    rho = construct_n_pairs_dm(n, 0.0, 0.25)
    rho, prob = _phase_check(rho, 2, 3, [(0, 5), (1, 4)], nq)
    rho_out = partial_trace(rho, [2, 3], nq)
    return {"fidelity": compute_fidelity_phi_plus(rho_out),
            "success_probability": prob}


def _solve_d5():
    """Mixed noise px=pz=0.06, N=5.

    For mixed noise, interleaving phase-flip and bit-flip distillation
    rounds is essential. A naive sequential approach (all phase checks
    then all bit checks) performs poorly because each check type amplifies
    the other error type through CNOT Z-error back-propagation.

    Interleaved protocol: phase, bit, phase, bit — each round alternately
    filters one error type, keeping both types under control.

    Pairs (outside-in): (0,9), (1,8), (2,7), (3,6), (4,5)=output
    Allocation: pairs 0,1 for phase checks; pairs 2,3 for bit checks.
    """
    n, nq = 5, 10
    rho = construct_n_pairs_dm(n, 0.06, 0.06)

    # Round 1: Phase check using pair (0, 9)
    rho, p1 = _phase_check(rho, 4, 5, [(0, 9)], nq)

    # Round 2: Bit check using pair (2, 7)
    rho, p2 = _bit_check(rho, 4, 5, [(2, 7)], nq)

    # Round 3: Phase check using pair (1, 8)
    rho, p3 = _phase_check(rho, 4, 5, [(1, 8)], nq)

    # Round 4: Bit check using pair (3, 6)
    rho, p4 = _bit_check(rho, 4, 5, [(3, 6)], nq)

    total_prob = p1 * p2 * p3 * p4
    rho_out = partial_trace(rho, [4, 5], nq)
    return {"fidelity": compute_fidelity_phi_plus(rho_out),
            "success_probability": total_prob}


def run_all():
    results = {
        "D1": _solve_d1(),
        "D2": _solve_d2(),
        "D3": _solve_d3(),
        "D4": _solve_d4(),
        "D5": _solve_d5(),
    }
    for sid, r in results.items():
        r["fidelity"] = round(r["fidelity"], 10)
        r["success_probability"] = round(r["success_probability"], 10)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    for sid, r in sorted(results.items()):
        print(f"{sid}: F={r['fidelity']:.6f}, p={r['success_probability']:.6f}")


if __name__ == "__main__":
    run_all()
