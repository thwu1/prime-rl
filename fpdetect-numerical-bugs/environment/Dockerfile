FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY app/fpmath.c /tmp/fpmath.c
RUN gcc -shared -fPIC -O2 -o /tmp/libfpmath.so /tmp/fpmath.c -lm

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    binutils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/libfpmath.so /app/libfpmath.so
COPY app/fpmath.h /app/fpmath.h
COPY app/audit_config.json /app/audit_config.json
