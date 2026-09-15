FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc libc6-dev binutils && rm -rf /var/lib/apt/lists/*
COPY cipher.c /tmp/cipher.c
RUN gcc -O2 -o /tmp/cipher_module /tmp/cipher.c && strip --strip-all /tmp/cipher_module

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip binutils file && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /tmp/cipher_module /app/cipher_module
RUN chmod +x /app/cipher_module

COPY scan_report.txt /app/scan_report.txt

WORKDIR /app
