FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY cstore.c /tmp/cstore.c
RUN gcc -O2 -o /tmp/cstore /tmp/cstore.c -lm && strip /tmp/cstore

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3-pip xxd strace ltrace binutils && rm -rf /var/lib/apt/lists/*
COPY --from=builder /tmp/cstore /app/cstore
RUN chmod 755 /app/cstore
RUN mkdir -p /app
