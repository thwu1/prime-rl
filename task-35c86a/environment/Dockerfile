FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    binutils-riscv64-linux-gnu \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY wormhole_grid.json /app/wormhole_grid.json
COPY noc_sim.c /app/noc_sim.c
COPY Makefile /app/Makefile
COPY tlb_spec.json /app/tlb_spec.json

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
