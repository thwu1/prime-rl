"""
Solve entanglement distillation for all edges in network.json.
Produces results.json, results.db, and OpenQASM 3.0 circuit files.
"""

import json
import os
import sqlite3
import sys
sys.path.insert(0, "/app")

from simulator import (initialize_pairs, apply_gate,
                        measure_and_postselect, compute_fidelity, check_locc)


def _run(n, px, pz, gates, measured_qubits, flag_func):
    """Run a distillation protocol and return (fidelity, success_prob)."""
    nq = 2 * n
    rho = initialize_pairs(n, px, pz)
    for gname, qubits in gates:
        rho = apply_gate(rho, gname, qubits, nq)
    rho_out, p = measure_and_postselect(rho, measured_qubits, flag_func, nq)
    f = compute_fidelity(rho_out, n - 1, n, nq)
    return f, p


def _make_qasm(n_qubits, gates, measured_qubits):
    """Generate an OpenQASM 3.0 circuit string."""
    lines = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        "",
        f"qubit[{n_qubits}] q;",
        f"bit[{len(measured_qubits)}] c;",
        "",
    ]
    for gname, qubits in gates:
        if len(qubits) == 1:
            lines.append(f"{gname} q[{qubits[0]}];")
        elif len(qubits) == 2:
            lines.append(f"{gname} q[{qubits[0]}], q[{qubits[1]}];")
    lines.append("")
    for i, mq in enumerate(measured_qubits):
        lines.append(f"c[{i}] = measure q[{mq}];")
    lines.append("")
    return "\n".join(lines)


def solve_e1():
    """Bit-flip pX=0.25, N=2."""
    gates = [("cx", [1, 0]), ("cx", [2, 3])]
    measured = [0, 3]
    flag = lambda o: o[0] == o[3]
    f, p = _run(2, 0.25, 0.0, gates, measured, flag)
    qasm = _make_qasm(4, gates, measured)
    return {"fidelity": f, "success_probability": p,
            "num_pairs": 2, "exceeds_threshold": f > 0.85}, qasm


def solve_e2():
    """Phase-flip pZ=0.25, N=2."""
    gates = [
        ("h", [0]), ("h", [1]), ("h", [2]), ("h", [3]),
        ("cx", [1, 0]), ("cx", [2, 3]),
        ("h", [1]), ("h", [2]),
    ]
    measured = [0, 3]
    flag = lambda o: o[0] == o[3]
    f, p = _run(2, 0.0, 0.25, gates, measured, flag)
    qasm = _make_qasm(4, gates, measured)
    return {"fidelity": f, "success_probability": p,
            "num_pairs": 2, "exceeds_threshold": f > 0.85}, qasm


def solve_e3():
    """Bit-flip pX=0.20, N=3."""
    gates = [
        ("cx", [2, 0]), ("cx", [3, 5]),
        ("cx", [2, 1]), ("cx", [3, 4]),
    ]
    measured = [0, 1, 4, 5]
    flag = lambda o: o[0] == o[5] and o[1] == o[4]
    f, p = _run(3, 0.20, 0.0, gates, measured, flag)
    qasm = _make_qasm(6, gates, measured)
    return {"fidelity": f, "success_probability": p,
            "num_pairs": 3, "exceeds_threshold": f > 0.93}, qasm


def solve_e4():
    """Phase-flip pZ=0.20, N=3."""
    gates = [
        ("h", [0]), ("h", [1]), ("h", [2]),
        ("h", [3]), ("h", [4]), ("h", [5]),
        ("cx", [2, 0]), ("cx", [3, 5]),
        ("cx", [2, 1]), ("cx", [3, 4]),
        ("h", [2]), ("h", [3]),
    ]
    measured = [0, 1, 4, 5]
    flag = lambda o: o[0] == o[5] and o[1] == o[4]
    f, p = _run(3, 0.0, 0.20, gates, measured, flag)
    qasm = _make_qasm(6, gates, measured)
    return {"fidelity": f, "success_probability": p,
            "num_pairs": 3, "exceeds_threshold": f > 0.93}, qasm


def solve_e5():
    """Mixed pX=0.10, pZ=0.05, N=5."""
    gates = [
        ("h", [4]), ("h", [5]),
        ("h", [1]), ("h", [8]),
        ("h", [0]), ("h", [9]),
        ("cx", [4, 1]), ("cx", [5, 8]),
        ("cx", [4, 0]), ("cx", [5, 9]),
        ("h", [4]), ("h", [5]),
        ("cx", [4, 3]), ("cx", [5, 6]),
        ("cx", [4, 2]), ("cx", [5, 7]),
    ]
    measured = [0, 1, 2, 3, 6, 7, 8, 9]

    def flag(o):
        return (o[1] == o[8] and o[0] == o[9]
                and o[3] == o[6] and o[2] == o[7])

    f, p = _run(5, 0.10, 0.05, gates, measured, flag)
    qasm = _make_qasm(10, gates, measured)
    return {"fidelity": f, "success_probability": p,
            "num_pairs": 5, "exceeds_threshold": f > 0.88}, qasm


def write_sqlite(results):
    """Create SQLite database with results table."""
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE results (
            edge_id TEXT PRIMARY KEY,
            fidelity REAL,
            success_probability REAL,
            num_pairs INTEGER,
            exceeds_threshold INTEGER
        )
    """)
    for eid, r in results.items():
        cur.execute(
            "INSERT INTO results VALUES (?, ?, ?, ?, ?)",
            (eid, r["fidelity"], r["success_probability"],
             r["num_pairs"], 1 if r["exceeds_threshold"] else 0)
        )
    conn.commit()
    conn.close()
    print(f"SQLite database written to {db_path}")


def main():
    os.makedirs("/app/circuits", exist_ok=True)

    solvers = {
        "E1": solve_e1,
        "E2": solve_e2,
        "E3": solve_e3,
        "E4": solve_e4,
        "E5": solve_e5,
    }

    results = {}
    for eid, solver in sorted(solvers.items()):
        r, qasm = solver()
        results[eid] = r

        qasm_path = f"/app/circuits/{eid}.qasm"
        with open(qasm_path, "w") as f:
            f.write(qasm)

        print(f"{eid}: F={r['fidelity']:.6f}  p={r['success_probability']:.6f}"
              f"  N={r['num_pairs']}  pass={r['exceeds_threshold']}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")

    write_sqlite(results)

    print(f"Circuit files written to /app/circuits/")


if __name__ == "__main__":
    main()
