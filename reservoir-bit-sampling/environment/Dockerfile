
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY bitpool.c /app/bitpool.c
COPY bitpool.h /app/bitpool.h
COPY Makefile /app/Makefile
COPY bitsource.py /app/bitsource.py
COPY sampler.py /app/sampler.py
COPY harness.py /app/harness.py

WORKDIR /app
