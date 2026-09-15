
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
COPY gen_hives.py /tmp/gen_hives.py
RUN python3 /tmp/gen_hives.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    libhivex-bin \
    xxd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/evidence /app/evidence

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
