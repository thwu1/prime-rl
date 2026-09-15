
# Stage 1: build binaries (source code stays only in this stage)
FROM ubuntu:24.04 AS builder
RUN apt-get update && apt-get install -y gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY src/license_check_alpha.c /tmp/license_check_alpha.c
COPY src/license_check_beta.c /tmp/license_check_beta.c
RUN gcc -O2 -static -s -fno-stack-protector -o /tmp/license_check_alpha /tmp/license_check_alpha.c
RUN gcc -O2 -static -s -fno-stack-protector -o /tmp/license_check_beta /tmp/license_check_beta.c

# Stage 2: runtime environment (no source code)
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    radare2 \
    gdb \
    binutils \
    strace \
    ltrace \
    gcc \
    libc6-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/license_check_alpha /app/license_check_alpha
COPY --from=builder /tmp/license_check_beta /app/license_check_beta
RUN chmod +x /app/license_check_alpha /app/license_check_beta

WORKDIR /app
