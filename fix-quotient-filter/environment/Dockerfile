
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3 \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY cqf.h /app/cqf.h
COPY cqf_hash.h /app/cqf_hash.h
COPY cqf_hash.c /app/cqf_hash.c
COPY Makefile /app/Makefile

WORKDIR /app
