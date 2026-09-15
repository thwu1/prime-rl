FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
    python3-pip \
    gcc \
    libc6-dev \
    jq \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY tweetnacl.c /app/tweetnacl.c
COPY tweetnacl.h /app/tweetnacl.h
COPY challenge.json /app/challenge.json

WORKDIR /app
