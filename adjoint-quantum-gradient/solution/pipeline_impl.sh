#!/usr/bin/env bash

set -e
cd /app

# 1. Initialise the SQLite database
sqlite3 /app/results.db < /app/schema.sql

# 2. Parse QASM, simulate, and insert results into the database
python3 -c "
import sys, os, glob, sqlite3
import numpy as np
sys.path.insert(0, '/app')
from qcsim.qasm_parser import parse_qasm
from qcsim.engine import simulate

db = sqlite3.connect('/app/results.db')

for qasm_file in sorted(glob.glob('/app/circuits/*.qasm')):
    name = os.path.splitext(os.path.basename(qasm_file))[0]
    circ = parse_qasm(qasm_file)
    state = simulate(circ)
    n_gates = len(circ.operations)
    db.execute('INSERT INTO circuits (name, n_qubits, n_gates) VALUES (?, ?, ?)',
               (name, circ.n_qubits, n_gates))
    cid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    probs = np.abs(state) ** 2
    for i in range(len(state)):
        if probs[i] > 0.001:
            db.execute(
                'INSERT INTO amplitudes (circuit_id, basis_state, real_part, imag_part, probability) VALUES (?, ?, ?, ?, ?)',
                (cid, int(i), float(state[i].real), float(state[i].imag), float(probs[i]))
            )
    db.commit()
db.close()
"

# 3. Export JSON report using sqlite3 CLI and jq
sqlite3 -cmd ".mode json" /app/results.db \
  "SELECT c.name, c.n_qubits, c.n_gates, a.basis_state, a.real_part, a.imag_part, a.probability FROM circuits c JOIN amplitudes a ON c.id = a.circuit_id ORDER BY c.name, a.basis_state;" \
  | jq '[group_by(.name) | .[] | {name: .[0].name, n_qubits: .[0].n_qubits, n_gates: .[0].n_gates, states: [.[] | {basis: .basis_state, prob: .probability, re: .real_part, im: .imag_part}]}]' \
  > /app/report.json
