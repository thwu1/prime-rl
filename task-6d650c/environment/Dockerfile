
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/benchmarks

COPY benchmarks/set_a.dat /app/benchmarks/set_a.dat
COPY benchmarks/set_b.txt /app/benchmarks/set_b.txt
COPY src/solver.c /app/src/solver.c
COPY src/Makefile /app/src/Makefile
COPY run.log /app/run.log

WORKDIR /app
