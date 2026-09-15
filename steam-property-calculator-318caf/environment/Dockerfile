FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/data

COPY src/if97_core.h /app/src/if97_core.h
COPY src/if97_core.c /app/src/if97_core.c
COPY src/Makefile /app/src/Makefile
COPY data/verification.csv /app/data/verification.csv

