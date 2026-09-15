FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip gcc make libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pfol /app/lib /app/data

COPY lib/adversary.c /app/lib/adversary.c
COPY lib/adversary.h /app/lib/adversary.h
COPY Makefile /app/Makefile
COPY data/scenarios.json /app/data/scenarios.json

