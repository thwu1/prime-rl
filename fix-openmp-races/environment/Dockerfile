
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y gcc g++ make clang libomp-dev python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY Makefile /app/Makefile
COPY src/histogram.c /app/src/histogram.c
COPY src/jacobi.c /app/src/jacobi.c
COPY src/nbody.c /app/src/nbody.c
COPY src/convolve.c /app/src/convolve.c
COPY src/prefix_scan.c /app/src/prefix_scan.c

WORKDIR /app
