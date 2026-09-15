FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /data
COPY generate_data.py /tmp/generate_data.py
RUN python3 /tmp/generate_data.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    sqlite3 \
    gnuplot-nox \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /data/buggy_rom.bin /app/buggy_rom.bin
COPY --from=builder /data/fixed_rom.pla /app/fixed_rom.pla
COPY --from=builder /data/test_vectors.csv /app/test_vectors.csv
COPY context.md /app/context.md

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
