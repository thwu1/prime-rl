
# Stage 1: Generate challenge data (private keys only exist in memory)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install cryptography==43.0.3 -q
COPY generate_challenge.py /tmp/gen.py
RUN python3 /tmp/gen.py /tmp/out

# Stage 2: Final image with only public challenge materials
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    openssl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/out/pki_audit /app/pki_audit

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 cryptography==43.0.3
