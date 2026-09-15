
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
    python3 \
    python3-pip \
    python3-numpy \
    python3-scipy \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY config.json /app/config.json
COPY hamiltonian.py /app/hamiltonian.py
COPY baseline_dense.py /app/baseline_dense.py
COPY sp2_solver.py /app/sp2_solver.py
