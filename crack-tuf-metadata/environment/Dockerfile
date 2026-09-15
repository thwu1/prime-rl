FROM python:3.12-slim AS builder

COPY setup_tuf_repo.py /tmp/setup_tuf_repo.py
RUN python3 /tmp/setup_tuf_repo.py /output

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    openssl \
    xxd \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /output/repository /app/repository
COPY --from=builder /output/keystore /app/keystore
COPY --from=builder /output/payload.bin /app/payload.bin

WORKDIR /app
