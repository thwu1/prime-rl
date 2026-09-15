
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder

RUN apt-get update && \
    apt-get install -y gcc && \
    rm -rf /var/lib/apt/lists/*

COPY allocator_ref.c /tmp/allocator_ref.c
RUN gcc -O2 -o /tmp/allocator_ref /tmp/allocator_ref.c && \
    strip /tmp/allocator_ref

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc binutils gdb strace ltrace && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /tmp/allocator_ref /app/allocator_ref
COPY config.py /app/config.py
COPY allocator_stub.py /app/allocator.py
COPY probe.py /app/probe.py

WORKDIR /app
