FROM ubuntu:24.04 AS builder
RUN apt-get update && apt-get install -y gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY evalx.c /tmp/evalx.c
RUN gcc -O2 -o /tmp/evalx /tmp/evalx.c -lm && strip --strip-all /tmp/evalx && rm /tmp/evalx.c

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential python3-pip gdb strace ltrace \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY --from=builder /tmp/evalx /app/evalx
COPY README.txt /app/README.txt

WORKDIR /app
