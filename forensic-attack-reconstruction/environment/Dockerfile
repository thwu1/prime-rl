
FROM python:3.12-slim AS builder
COPY setup_encryption.py /tmp/setup_encryption.py
RUN python3 /tmp/setup_encryption.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    file \
    xxd \
    jq \
    yara \
    && rm -rf /var/lib/apt/lists/*

COPY evidence/ /app/evidence/
COPY --from=builder /tmp/encrypted_exfil.bin /app/evidence/encrypted_exfil.bin

WORKDIR /app
