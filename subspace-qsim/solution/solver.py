#!/usr/bin/env python3

import json
import sqlite3
import struct
import hashlib
import tomllib
import numpy as np


# ---------------------------------------------------------------------------
# Circuit loading from SQLite + binary params file
# ---------------------------------------------------------------------------

def load_circuit(db_path, bin_path):
    with open(bin_path, 'rb') as f:
        params_bin = f.read()

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("SELECT num_qubits FROM circuit_meta")
    n = c.fetchone()[0]

    c.execute(
        "SELECT gate_id, gate_type, custom_matrix_id "
        "FROM gates ORDER BY gate_order"
    )
    raw = c.fetchall()

    gates = []
    for gid, gtype, cmid in raw:
        g = {"name": gtype}

        c.execute(
            "SELECT qubit FROM gate_targets "
            "WHERE gate_id=? ORDER BY target_order",
            (gid,),
        )
        g["qubits"] = [r[0] for r in c.fetchall()]

        c.execute(
            "SELECT bin_offset FROM gate_params "
            "WHERE gate_id=? ORDER BY param_order",
            (gid,),
        )
        offsets = [r[0] for r in c.fetchall()]
        if offsets:
            g["params"] = [
                struct.unpack_from('<d', params_bin, off)[0] for off in offsets
            ]

        c.execute(
            "SELECT control_qubit, control_value FROM gate_controls "
            "WHERE gate_id=?",
            (gid,),
        )
        ct = c.fetchall()
        if ct:
            g["controls"] = [[r[0], r[1]] for r in ct]

        if cmid is not None:
            c.execute(
                "SELECT row_idx, col_idx, real_part, imag_part "
                "FROM custom_matrices WHERE matrix_id=?",
                (cmid,),
            )
            ent = c.fetchall()
            dim = max(r[0] for r in ent) + 1
            mr = [[0.0] * dim for _ in range(dim)]
            mi = [[0.0] * dim for _ in range(dim)]
            for ri, ci, rp, ip in ent:
                mr[ri][ci] = rp
                mi[ri][ci] = ip
            g["matrix_real"] = mr
            g["matrix_imag"] = mi

        gates.append(g)

    conn.close()
    return {"num_qubits": n, "gates": gates}


# ---------------------------------------------------------------------------
# Bit-manipulation primitives
# ---------------------------------------------------------------------------

def lmove(b, mask, k):
    return ((b & ~mask) << k) | (b & mask)


def group_shift(locations):
    masks, shift_lens = [], []
    k_prv = -2
    for k in locations:
        if k == k_prv + 1:
            shift_lens[-1] += 1
        else:
            masks.append((1 << k) - 1)
            shift_lens.append(1)
        k_prv = k
    return masks, shift_lens


def complement_group_shift(n, locations):
    masks, shift_lens = [], []
    k_prv = -2
    loc_set = set(locations)
    for k in range(n):
        if k in loc_set:
            continue
        if k == k_prv + 1:
            shift_lens[-1] += 1
        else:
            masks.append((1 << k) - 1)
            shift_lens.append(1)
        k_prv = k
    return masks, shift_lens


class BitSubspace:
    def __init__(self, n, locations, complement=False):
        locations = sorted(locations)
        if complement:
            masks, shift_lens = complement_group_shift(n, locations)
            self.size = 1 << len(locations)
        else:
            masks, shift_lens = group_shift(locations)
            self.size = 1 << (n - len(locations))
        self.masks = masks
        self.shift_lens = shift_lens
        self.n_shifts = len(masks)

    def __getitem__(self, i):
        index = i
        for s in range(self.n_shifts):
            index = lmove(index, self.masks[s], self.shift_lens[s])
        return index

    def __len__(self):
        return self.size

    def __iter__(self):
        for i in range(self.size):
            yield self[i]


# ---------------------------------------------------------------------------
# Gate definitions
# ---------------------------------------------------------------------------

GATES = {
    "H": np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2),
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    "S": np.array([[1, 0], [0, 1j]], dtype=complex),
    "T": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
}


def _rotation(name, theta):
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    if name == "Rx":
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)
    if name == "Ry":
        return np.array([[c, -s], [s, c]], dtype=complex)
    if name == "Rz":
        return np.array(
            [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]],
            dtype=complex,
        )
    raise ValueError(name)


# ---------------------------------------------------------------------------
# Gate application via subspace iteration
# ---------------------------------------------------------------------------

def apply_gate(state, U, targets, n_qubits, controls=None, ctrl_vals=None):
    targets_sorted = sorted(targets)

    if controls is not None:
        all_locs = sorted(set(targets_sorted) | set(controls))
        offset = sum(1 << c for c, v in zip(controls, ctrl_vals) if v == 1)
    else:
        all_locs = targets_sorted
        offset = 0

    subspace = BitSubspace(n_qubits, all_locs, complement=False)
    comspace = BitSubspace(n_qubits, targets_sorted, complement=True)

    com_indices = [c for c in comspace]
    k = len(com_indices)
    sub_buf = np.empty(k, dtype=complex)

    for s_idx in subspace:
        for i in range(k):
            sub_buf[i] = state[s_idx + com_indices[i] + offset]
        new_sub = U @ sub_buf
        for i in range(k):
            state[s_idx + com_indices[i] + offset] = new_sub[i]

    return state


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate(circuit):
    n = circuit["num_qubits"]
    state = np.zeros(2**n, dtype=complex)
    state[0] = 1.0

    for gate in circuit["gates"]:
        name = gate["name"]
        qubits = gate["qubits"]
        params = gate.get("params", [])
        controls_raw = gate.get("controls", None)

        controls = None
        ctrl_vals = None
        if controls_raw is not None:
            controls = [c[0] for c in controls_raw]
            ctrl_vals = [c[1] for c in controls_raw]

        if name == "CUSTOM":
            U = np.array(gate["matrix_real"], dtype=complex) + 1j * np.array(
                gate["matrix_imag"], dtype=complex
            )
        elif name in ("Rx", "Ry", "Rz"):
            U = _rotation(name, params[0])
        else:
            U = GATES[name]

        state = apply_gate(state, U, qubits, n, controls, ctrl_vals)

    return state


# ---------------------------------------------------------------------------
# Observables
# ---------------------------------------------------------------------------

def pauli_expectation(state, terms, n_qubits):
    PAULI = {
        "X": np.array([[0, 1], [1, 0]], dtype=complex),
        "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
        "Z": np.array([[1, 0], [0, -1]], dtype=complex),
    }
    phi = state.copy()
    for term in terms:
        phi = apply_gate(phi, PAULI[term["pauli"]], [term["qubit"]], n_qubits)
    return float(np.real(np.conj(state) @ phi))


# ---------------------------------------------------------------------------
# Entanglement entropy
# ---------------------------------------------------------------------------

def entanglement_entropy(state, partition_A, n_qubits):
    n_A = len(partition_A)
    partition_B = sorted(set(range(n_qubits)) - set(partition_A))
    dim_A = 2**n_A
    dim_B = 2 ** (n_qubits - n_A)
    sorted_A = sorted(partition_A)

    M = np.zeros((dim_A, dim_B), dtype=complex)
    for idx in range(2**n_qubits):
        a = 0
        for i, q in enumerate(sorted_A):
            a |= ((idx >> q) & 1) << i
        b = 0
        for i, q in enumerate(partition_B):
            b |= ((idx >> q) & 1) << i
        M[a, b] = state[idx]

    _, s, _ = np.linalg.svd(M, full_matrices=False)
    p = s**2
    p = p[p > 1e-30]
    return float(-np.sum(p * np.log(p)))


# ---------------------------------------------------------------------------
# State hash
# ---------------------------------------------------------------------------

def compute_state_hash(state):
    """SHA-256 of state vector serialized as LE float64 (re,im) pairs."""
    buf = bytearray()
    for i in range(len(state)):
        buf.extend(struct.pack('<d', state[i].real))
        buf.extend(struct.pack('<d', state[i].imag))
    return hashlib.sha256(bytes(buf)).hexdigest()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    circuit = load_circuit("/app/circuit.db", "/app/params.bin")

    with open("/app/observables.toml", 'rb') as f:
        obs = tomllib.load(f)

    state = simulate(circuit)
    n = circuit["num_qubits"]

    amplitudes = {}
    for i in range(2**n):
        amplitudes[str(i)] = [float(state[i].real), float(state[i].imag)]

    exp_vals = []
    total_energy = 0.0
    for observable in obs["observables"]:
        val = observable["coefficient"] * pauli_expectation(
            state, observable["terms"], n
        )
        exp_vals.append(float(val))
        total_energy += val

    partition_A = list(range(n // 2))
    entropy = entanglement_entropy(state, partition_A, n)

    state_hash = compute_state_hash(state)

    results = {
        "amplitudes": amplitudes,
        "expectation_values": exp_vals,
        "total_energy": float(total_energy),
        "entanglement_entropy": entropy,
        "state_hash": state_hash,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(f"State hash: {state_hash}")


if __name__ == "__main__":
    main()
