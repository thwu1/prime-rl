
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    linux-libc-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY pledge.h /app/pledge.h
COPY pledge_stub.c /app/pledge.c
COPY Makefile /app/Makefile
COPY test_harness.c /app/test_harness.c

WORKDIR /app
