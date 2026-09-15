
# Stage 1: compile the reference binary
FROM ubuntu:24.04 AS builder
RUN apt-get update && apt-get install -y gcc zlib1g-dev && rm -rf /var/lib/apt/lists/*
COPY arkv.c /tmp/arkv.c
RUN gcc -O2 -o /tmp/arkv /tmp/arkv.c -lz

# Stage 2: task environment
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    zlib1g \
    strace ltrace \
    binutils xxd file \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /tmp/arkv /app/arkv
RUN strip /app/arkv && chmod +x /app/arkv
COPY README.txt /app/README.txt
