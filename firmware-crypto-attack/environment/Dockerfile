FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip && rm -rf /var/lib/apt/lists/*
RUN pip3 install cryptography==44.0.0 sympy==1.13.3
COPY gen_challenge.py /tmp/gen_challenge.py
RUN mkdir -p /app && python3 /tmp/gen_challenge.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    openssl \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/repository /app/repository
COPY --from=builder /app/.flag_verification_hash /app/.flag_verification_hash

WORKDIR /app

