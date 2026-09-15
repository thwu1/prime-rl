FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install numpy==2.1.3

RUN mkdir -p /app/benchmarks /app/results

COPY circuit.py /app/circuit.py
COPY targets.json /app/targets.json
COPY bench_a.qasm /app/benchmarks/bench_a.qasm
COPY bench_b.qasm /app/benchmarks/bench_b.qasm
COPY bench_c.qasm /app/benchmarks/bench_c.qasm
COPY bench_d.qasm /app/benchmarks/bench_d.qasm
COPY bench_e.qasm /app/benchmarks/bench_e.qasm

WORKDIR /app
