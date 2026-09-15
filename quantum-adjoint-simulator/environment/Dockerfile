FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip gcc libc6-dev jq make sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/quantum_sim /app/circuits /app/results

COPY app/quantum_sim/__init__.py /app/quantum_sim/__init__.py
COPY app/quantum_sim/gates.py /app/quantum_sim/gates.py
COPY app/quantum_sim/kernel.c /app/quantum_sim/kernel.c
COPY app/run_circuit.py /app/run_circuit.py
COPY app/Makefile /app/Makefile
COPY app/circuits/bell_z0.json /app/circuits/bell_z0.json
COPY app/circuits/rx_z0.json /app/circuits/rx_z0.json
COPY app/circuits/vqe_2q.json /app/circuits/vqe_2q.json

WORKDIR /app
