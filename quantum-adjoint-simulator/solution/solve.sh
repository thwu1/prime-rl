#!/bin/bash

pip3 install numpy==2.1.3 -q

# Ensure the package directory exists
mkdir -p /app/quantum_sim

# Deploy Python modules
cp /solution/gates_impl.py /app/quantum_sim/gates.py
cp /solution/engine_impl.py /app/quantum_sim/engine.py
cp /solution/circuit_impl.py /app/quantum_sim/circuit.py
cp /solution/differentiation_impl.py /app/quantum_sim/differentiation.py

# Deploy the CLI
cp /solution/run_circuit_impl.py /app/run_circuit.py

# Deploy and compile C kernel
cp /solution/kernel_impl.c /app/quantum_sim/kernel.c
cd /app && make build
