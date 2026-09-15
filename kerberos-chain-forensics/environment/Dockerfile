
FROM python:3.12-slim AS builder
RUN pip install pycryptodome==3.21.0 cryptography==44.0.0
COPY setup_environment.py /tmp/setup_environment.py
RUN python3 /tmp/setup_environment.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    openssl \
    jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/evidence/ /app/evidence/
RUN mkdir -p /app/answers

WORKDIR /app
