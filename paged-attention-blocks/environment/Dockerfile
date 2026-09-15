
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    valgrind \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY blockpool.h /app/blockpool.h
COPY blockpool.c /app/blockpool.c
COPY Makefile /app/Makefile
COPY block_manager.py /app/block_manager.py
COPY spec.md /app/spec.md

WORKDIR /app
