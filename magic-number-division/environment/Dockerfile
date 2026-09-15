FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY challenge.c /tmp/challenge.c
RUN gcc -O2 -o /tmp/challenge /tmp/challenge.c && strip -s /tmp/challenge

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    binutils \
    gdb \
    radare2 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /tmp/challenge /app/challenge
COPY spec.json /app/spec.json
COPY readme.txt /app/README.txt

WORKDIR /app
