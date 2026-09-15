#!/usr/bin/env python3
"""Build-time script: convert circuit JSON to normalized SQLite database + binary params file."""
import json
import sqlite3
import struct
import sys


def main():
    circuit_path = sys.argv[1]
    db_path = sys.argv[2]
    bin_path = sys.argv[3]

    with open(circuit_path) as f:
        circuit = json.load(f)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("CREATE TABLE circuit_meta (num_qubits INTEGER NOT NULL)")
    c.execute("INSERT INTO circuit_meta VALUES (?)", (circuit["num_qubits"],))

    c.execute("""CREATE TABLE gates (
        gate_id INTEGER PRIMARY KEY,
        gate_order INTEGER NOT NULL,
        gate_type TEXT NOT NULL,
        custom_matrix_id INTEGER
    )""")

    c.execute("""CREATE TABLE gate_targets (
        gate_id INTEGER NOT NULL,
        qubit INTEGER NOT NULL,
        target_order INTEGER NOT NULL,
        PRIMARY KEY (gate_id, target_order)
    )""")

    c.execute("""CREATE TABLE gate_params (
        gate_id INTEGER NOT NULL,
        param_order INTEGER NOT NULL,
        bin_offset INTEGER NOT NULL,
        PRIMARY KEY (gate_id, param_order)
    )""")

    c.execute("""CREATE TABLE gate_controls (
        gate_id INTEGER NOT NULL,
        control_qubit INTEGER NOT NULL,
        control_value INTEGER NOT NULL,
        PRIMARY KEY (gate_id, control_qubit)
    )""")

    c.execute("""CREATE TABLE custom_matrices (
        matrix_id INTEGER NOT NULL,
        row_idx INTEGER NOT NULL,
        col_idx INTEGER NOT NULL,
        real_part REAL NOT NULL,
        imag_part REAL NOT NULL,
        PRIMARY KEY (matrix_id, row_idx, col_idx)
    )""")

    params_data = bytearray()

    custom_id = 0
    for order, gate in enumerate(circuit["gates"]):
        mid = None
        if gate["name"] == "CUSTOM":
            mid = custom_id
            mr = gate["matrix_real"]
            mi = gate["matrix_imag"]
            dim = len(mr)
            for r in range(dim):
                for k in range(dim):
                    c.execute(
                        "INSERT INTO custom_matrices VALUES (?,?,?,?,?)",
                        (mid, r, k, mr[r][k], mi[r][k]),
                    )
            custom_id += 1

        c.execute(
            "INSERT INTO gates VALUES (?,?,?,?)",
            (order, order, gate["name"], mid),
        )

        for t, q in enumerate(gate["qubits"]):
            c.execute(
                "INSERT INTO gate_targets VALUES (?,?,?)", (order, q, t)
            )

        for p, v in enumerate(gate.get("params", [])):
            offset = len(params_data)
            params_data.extend(struct.pack('<d', v))
            c.execute(
                "INSERT INTO gate_params VALUES (?,?,?)", (order, p, offset)
            )

        for ctrl in gate.get("controls", []):
            c.execute(
                "INSERT INTO gate_controls VALUES (?,?,?)",
                (order, ctrl[0], ctrl[1]),
            )

    conn.commit()
    conn.close()

    with open(bin_path, 'wb') as f:
        f.write(params_data)


if __name__ == "__main__":
    main()
