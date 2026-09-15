FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data/reference

COPY data/materials.json /app/data/materials.json
COPY data/reference/square_tm.ref /app/data/reference/square_tm.ref
COPY data/reference/triangular_tm.ref /app/data/reference/triangular_tm.ref
COPY data/reference/triangular_optimal.ref /app/data/reference/triangular_optimal.ref

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
