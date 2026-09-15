
# Stage 1: Build correct LULESH and generate reference outputs + GCI
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y g++ make python3 && rm -rf /var/lib/apt/lists/*
COPY correct_src/ /tmp/build/
COPY compute_ref_gci.py /tmp/compute_ref_gci.py
RUN cd /tmp/build && make 2>&1 && \
    mkdir -p /reference/convergence && \
    ./lulesh2.0 -s 10 -i 100 > /reference/output_s10_i100.txt 2>&1 && \
    ./lulesh2.0 -s 15 -i 50 > /reference/output_s15_i50.txt 2>&1 && \
    ./lulesh2.0 -s 8 -i 50 > /reference/convergence/output_s8_i50.txt 2>&1 && \
    ./lulesh2.0 -s 12 -i 50 > /reference/convergence/output_s12_i50.txt 2>&1 && \
    ./lulesh2.0 -s 16 -i 50 > /reference/convergence/output_s16_i50.txt 2>&1 && \
    ./lulesh2.0 -s 20 -i 50 > /reference/convergence/output_s20_i50.txt 2>&1 && \
    python3 /tmp/compute_ref_gci.py && \
    rm -rf /tmp/build /tmp/compute_ref_gci.py

# Stage 2: Set up task environment with buggy source
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y g++ make python3-pip gdb valgrind && \
    rm -rf /var/lib/apt/lists/*

# Copy reference outputs and GCI reference (NOT the correct source code)
COPY --from=builder /reference/ /reference/

# Copy buggy LULESH source to /app/
COPY buggy_src/ /app/

WORKDIR /app
