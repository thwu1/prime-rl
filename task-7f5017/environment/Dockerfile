FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    racket \
    gcc \
    clang \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/test-programs /app/input-files

COPY starter/irs.rkt /app/irs.rkt
COPY starter/interpreters.rkt /app/interpreters.rkt
COPY starter/system.rkt /app/system.rkt
COPY starter/main.rkt /app/main.rkt
COPY starter/runtime.c /app/runtime.c
COPY starter/compile.rkt /app/compile.rkt
COPY starter/test-programs/ /app/test-programs/
COPY starter/input-files/ /app/input-files/

WORKDIR /app
