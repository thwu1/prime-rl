FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3 gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY generate_archive.py /tmp/generate_archive.py
RUN mkdir -p /app && python3 /tmp/generate_archive.py
RUN gcc -std=c99 -O1 -s -o /app/vfs_hasher /tmp/vfs_hasher.c

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xxd \
    file \
    binutils \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/archive.vfs /app/archive.vfs
COPY --from=builder /app/vfs_hasher /app/vfs_hasher
RUN chmod +x /app/vfs_hasher

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
