#!/bin/bash

set -e

pip3 install numpy==2.1.3 -q

# Deploy engine and circuits to /app
cp /solution/engine_impl.py /app/engine.py
cp /solution/circuits_impl.py /app/circuits.py

cd /app

# Validate all scenarios by computing fidelities
python3 -c "
import json
from engine import run_distillation, validate_locc
from circuits import get_circuit

with open('scenarios.json') as f:
    scenarios = json.load(f)['scenarios']

for s in scenarios:
    circuit = get_circuit(s['id'])
    assert validate_locc(circuit, s['N']), f\"{s['id']}: LOCC violation\"
    result = run_distillation(circuit, s['N'], s['noise'])
    fid = result['fidelity']
    psc = result['success_probability']
    thr = s['threshold']
    status = 'PASS' if fid >= thr else 'FAIL'
    print(f\"{s['id']}: fidelity={fid:.6f}  threshold={thr}  p_success={psc:.6f}  [{status}]\")
    assert fid >= thr, f\"{s['id']}: fidelity {fid:.6f} < threshold {thr}\"

print('All scenarios passed.')
"
