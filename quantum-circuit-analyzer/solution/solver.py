#!/usr/bin/env python3

"""Quantum circuit compilation and resource characterization — reference solution."""

import json
import os
import re
import sqlite3
from glob import glob

import numpy as np

# ---------------------------------------------------------------------------
# Gate matrices
# ---------------------------------------------------------------------------

GATES = {
    "H": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "Sdg": np.array([[1, 0], [0, -1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    "Tdg": np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=complex),
    "CNOT": np.array(
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], dtype=complex,
    ),
    "CZ": np.array(
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, -1]], dtype=complex,
    ),
    "SWAP": np.array(
        [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex,
    ),
}

_ccx = np.eye(8, dtype=complex)
_ccx[6, 6] = 0
_ccx[7, 7] = 0
_ccx[6, 7] = 1
_ccx[7, 6] = 1
GATES["CCX"] = _ccx

QASM_MAP = {
    "h": "H", "x": "X", "y": "Y", "z": "Z",
    "s": "S", "sdg": "Sdg", "t": "T", "tdg": "Tdg",
    "cx": "CNOT", "cz": "CZ", "swap": "SWAP", "ccx": "CCX",
}


# ---------------------------------------------------------------------------
# OpenQASM 2.0 parser
# ---------------------------------------------------------------------------

def parse_qasm(filepath):
    name = os.path.splitext(os.path.basename(filepath))[0]
    num_qubits = None
    gates = []

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if (not line or line.startswith("//")
                    or line.startswith("OPENQASM")
                    or line.startswith("include")
                    or line.startswith("creg")):
                continue

            m = re.match(r"qreg\s+\w+\[(\d+)\];", line)
            if m:
                num_qubits = int(m.group(1))
                continue

            m = re.match(r"(\w+)\s+(.*);", line)
            if m:
                gate_qasm = m.group(1)
                args_str = m.group(2)
                gate_name = QASM_MAP.get(gate_qasm)
                if gate_name is None:
                    continue
                targets = [int(x) for x in re.findall(r"\[(\d+)\]", args_str)]
                gates.append({"gate": gate_name, "targets": targets})

    return {"name": name, "num_qubits": num_qubits, "gates": gates}


# ---------------------------------------------------------------------------
# Operator construction & simulation
# ---------------------------------------------------------------------------

def build_operator(gate_matrix, qubits, num_qubits):
    n = num_qubits
    dim = 2 ** n
    ng = len(qubits)
    op = np.zeros((dim, dim), dtype=complex)

    for i in range(dim):
        for j in range(dim):
            match = True
            for q in range(n):
                if q not in qubits:
                    if ((i >> (n - 1 - q)) & 1) != ((j >> (n - 1 - q)) & 1):
                        match = False
                        break
            if not match:
                continue
            gi = gj = 0
            for k, q in enumerate(qubits):
                gi |= ((i >> (n - 1 - q)) & 1) << (ng - 1 - k)
                gj |= ((j >> (n - 1 - q)) & 1) << (ng - 1 - k)
            op[i, j] = gate_matrix[gi, gj]

    return op


def simulate(circuit):
    n = circuit["num_qubits"]
    state = np.zeros(2 ** n, dtype=complex)
    state[0] = 1.0
    for g in circuit["gates"]:
        mat = GATES[g["gate"]]
        op = build_operator(mat, g["targets"], n)
        state = op @ state
    return state


# ---------------------------------------------------------------------------
# Gate-set restriction (decomposition to Clifford+T)
# ---------------------------------------------------------------------------

ALLOWED = {"H", "X", "CNOT", "T", "Tdg", "S", "Sdg"}


def decompose_ccx(c1, c2, tgt):
    return [
        {"gate": "H", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c2, tgt]},
        {"gate": "Tdg", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c1, tgt]},
        {"gate": "T", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c2, tgt]},
        {"gate": "Tdg", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c1, tgt]},
        {"gate": "T", "targets": [c2]},
        {"gate": "T", "targets": [tgt]},
        {"gate": "H", "targets": [tgt]},
        {"gate": "CNOT", "targets": [c1, c2]},
        {"gate": "T", "targets": [c1]},
        {"gate": "Tdg", "targets": [c2]},
        {"gate": "CNOT", "targets": [c1, c2]},
    ]


def restrict_gate_set(circuit):
    new_gates = []
    for g in circuit["gates"]:
        gn = g["gate"]
        if gn in ALLOWED:
            new_gates.append(g)
        elif gn == "Y":
            q = g["targets"][0]
            new_gates.extend([
                {"gate": "S", "targets": [q]},
                {"gate": "X", "targets": [q]},
                {"gate": "Sdg", "targets": [q]},
            ])
        elif gn == "Z":
            q = g["targets"][0]
            new_gates.extend([
                {"gate": "S", "targets": [q]},
                {"gate": "S", "targets": [q]},
            ])
        elif gn == "CZ":
            q1, q2 = g["targets"]
            new_gates.extend([
                {"gate": "H", "targets": [q2]},
                {"gate": "CNOT", "targets": [q1, q2]},
                {"gate": "H", "targets": [q2]},
            ])
        elif gn == "SWAP":
            q1, q2 = g["targets"]
            new_gates.extend([
                {"gate": "CNOT", "targets": [q1, q2]},
                {"gate": "CNOT", "targets": [q2, q1]},
                {"gate": "CNOT", "targets": [q1, q2]},
            ])
        elif gn == "CCX":
            c1, c2, tgt = g["targets"]
            new_gates.extend(decompose_ccx(c1, c2, tgt))
    return {
        "name": circuit["name"],
        "num_qubits": circuit["num_qubits"],
        "gates": new_gates,
    }


# ---------------------------------------------------------------------------
# T-count (naive and optimized)
# ---------------------------------------------------------------------------

def naive_t_count(circuit):
    return sum(1 for g in circuit["gates"] if g["gate"] in ("T", "Tdg"))


_DIAG_PHASE = {
    "T": np.pi / 4, "Tdg": -np.pi / 4,
    "S": np.pi / 2, "Sdg": -np.pi / 2,
}


def optimized_t_count(circuit):
    """T+Tdg count after merging consecutive diagonal single-qubit gates per qubit."""
    n = circuit["num_qubits"]
    gates = circuit["gates"]
    tl = [[] for _ in range(n)]
    for gi, g in enumerate(gates):
        for q in g["targets"]:
            tl[q].append(gi)

    total = 0
    for q in range(n):
        i = 0
        while i < len(tl[q]):
            g = gates[tl[q][i]]
            if g["gate"] in _DIAG_PHASE and len(g["targets"]) == 1:
                phase = 0.0
                while i < len(tl[q]):
                    g2 = gates[tl[q][i]]
                    if g2["gate"] in _DIAG_PHASE and len(g2["targets"]) == 1:
                        phase += _DIAG_PHASE[g2["gate"]]
                        i += 1
                    else:
                        break
                k = round(phase / (np.pi / 4)) % 8
                if k % 2 == 1:
                    total += 1
            else:
                i += 1
    return total


# ---------------------------------------------------------------------------
# State metrics
# ---------------------------------------------------------------------------

def state_to_probs(state, n):
    probs = {}
    for i, amp in enumerate(state):
        p = float(abs(amp) ** 2)
        if p > 1e-10:
            probs[format(i, f"0{n}b")] = round(p, 10)
    return probs


def entanglement_entropy(state, n):
    """Standard bipartite entropy for cut A={0..floor(n/2)-1}."""
    na = n // 2
    nb = n - na
    psi = state.reshape(2 ** na, 2 ** nb)
    rho = psi @ psi.conj().T
    eigs = np.linalg.eigvalsh(rho)
    s = 0.0
    for lam in eigs:
        if lam > 1e-15:
            s -= lam * np.log2(lam)
    return float(s)


def entropy_bipartition(state, n, part_a):
    """Entanglement entropy for an arbitrary bipartition."""
    part_b = sorted(set(range(n)) - set(part_a))
    na, nb = len(part_a), len(part_b)
    perm = list(part_a) + part_b
    tensor = state.reshape([2] * n).transpose(perm)
    psi = tensor.reshape(2 ** na, 2 ** nb)
    rho = psi @ psi.conj().T
    eigs = np.linalg.eigvalsh(rho)
    s = 0.0
    for lam in eigs:
        if lam > 1e-15:
            s -= lam * np.log2(lam)
    return float(s)


def all_bipartitions(n):
    """All non-trivial bipartitions with qubit 0 in part_a (canonical)."""
    result = []
    for mask in range(2 ** (n - 1)):
        part_a = [0]
        for bit in range(n - 1):
            if mask & (1 << bit):
                part_a.append(bit + 1)
        if len(part_a) < n:
            result.append(part_a)
    return result


def max_bipartite_entropy(state, n):
    """Maximum entanglement entropy over all non-trivial bipartitions."""
    return max(entropy_bipartition(state, n, bp) for bp in all_bipartitions(n))


def meyer_wallach_measure(state, n):
    """Q = 2(1 - (1/n) sum_k Tr(rho_k^2))."""
    total_purity = 0.0
    for k in range(n):
        perm = [k] + sorted(set(range(n)) - {k})
        tensor = state.reshape([2] * n).transpose(perm)
        psi = tensor.reshape(2, 2 ** (n - 1))
        rho_k = psi @ psi.conj().T
        total_purity += np.real(np.trace(rho_k @ rho_k))
    return float(2.0 * (1.0 - total_purity / n))


def compute_entanglement_class(state, n):
    """Classify: product / biseparable / genuine."""
    bps = all_bipartitions(n)
    entropies = [entropy_bipartition(state, n, bp) for bp in bps]
    if all(s < 1e-10 for s in entropies):
        return "product"
    if all(s > 1e-10 for s in entropies):
        return "genuine"
    return "biseparable"


def magic_fraction(state, n):
    """mu = 1 - Xi/2^n where Xi = sum_P <psi|P|psi>^4."""
    paulis = [
        np.eye(2, dtype=complex),
        np.array([[0, 1], [1, 0]], dtype=complex),
        np.array([[0, -1j], [1j, 0]], dtype=complex),
        np.array([[1, 0], [0, -1]], dtype=complex),
    ]
    xi = 0.0
    for idx in range(4 ** n):
        P = np.array([[1.0]], dtype=complex)
        temp = idx
        for _q in range(n):
            P = np.kron(P, paulis[temp & 3])
            temp >>= 2
        exp_val = np.real(state.conj() @ P @ state)
        xi += exp_val ** 4
    return float(1.0 - xi / (2 ** n))


# ---------------------------------------------------------------------------
# Main analysis pipeline
# ---------------------------------------------------------------------------

def analyze(circuit):
    n = circuit["num_qubits"]

    state = simulate(circuit)
    probs = state_to_probs(state, n)

    restricted = restrict_gate_set(circuit)
    r_state = simulate(restricted)
    r_probs = state_to_probs(r_state, n)

    ntc = naive_t_count(restricted)
    otc = optimized_t_count(restricted)
    be = entanglement_entropy(state, n)
    mbe = max_bipartite_entropy(state, n)
    mw = meyer_wallach_measure(state, n)
    ec = compute_entanglement_class(state, n)
    mf = magic_fraction(state, n)

    return {
        "probabilities": probs,
        "decomposed_probabilities": r_probs,
        "naive_t_count": ntc,
        "optimized_t_count": otc,
        "bipartite_entropy": round(be, 6),
        "max_bipartite_entropy": round(mbe, 6),
        "meyer_wallach_measure": round(mw, 6),
        "entanglement_class": ec,
        "magic_fraction": round(mf, 6),
    }


def main():
    circuits_dir = "/app/circuits"
    results = {}
    parsed = {}

    for path in sorted(glob(os.path.join(circuits_dir, "*.qasm"))):
        circuit = parse_qasm(path)
        name = circuit["name"]
        print(f"Analyzing {name} ...")
        parsed[name] = circuit
        results[name] = analyze(circuit)

    # Store in SQLite
    db_path = "/app/analysis.db"
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS circuit_analysis ("
        "  circuit_name TEXT PRIMARY KEY,"
        "  num_qubits INTEGER,"
        "  probabilities TEXT,"
        "  equiv_probabilities TEXT,"
        "  naive_t_count INTEGER,"
        "  optimized_t_count INTEGER,"
        "  bipartite_entropy REAL,"
        "  max_bipartite_entropy REAL,"
        "  meyer_wallach_measure REAL,"
        "  entanglement_class TEXT,"
        "  magic_fraction REAL"
        ")"
    )
    for name, data in results.items():
        cur.execute(
            "INSERT OR REPLACE INTO circuit_analysis VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                name,
                parsed[name]["num_qubits"],
                json.dumps(data["probabilities"]),
                json.dumps(data["decomposed_probabilities"]),
                data["naive_t_count"],
                data["optimized_t_count"],
                data["bipartite_entropy"],
                data["max_bipartite_entropy"],
                data["meyer_wallach_measure"],
                data["entanglement_class"],
                data["magic_fraction"],
            ),
        )
    conn.commit()
    conn.close()
    print(f"Database written to {db_path}")

    # Export to JSON
    out = "/app/results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results written to {out}")


if __name__ == "__main__":
    main()
