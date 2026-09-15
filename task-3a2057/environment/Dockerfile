FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    build-essential \
    binutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY benchmarks.fpcore /app/benchmarks.fpcore
COPY naive.c /app/naive.c
COPY naive.h /app/naive.h

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4 mpmath==1.3.0
