FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/circuits

COPY circuits/ghz_4.qasm /app/circuits/ghz_4.qasm
COPY circuits/grover_3.qasm /app/circuits/grover_3.qasm
COPY circuits/deutsch_jozsa_4.qasm /app/circuits/deutsch_jozsa_4.qasm
COPY circuits/toffoli_cascade.qasm /app/circuits/toffoli_cascade.qasm
COPY circuits/mixed_gates_5.qasm /app/circuits/mixed_gates_5.qasm
COPY circuits/phase_gadget_4.qasm /app/circuits/phase_gadget_4.qasm

WORKDIR /app
