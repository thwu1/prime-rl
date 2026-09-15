
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 gcc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY heapservice.c /tmp/heapservice.c
RUN gcc -O1 -o /app/heapservice /tmp/heapservice.c && \
    strip /app/heapservice && \
    rm /tmp/heapservice.c

COPY generate_snapshots.py /tmp/generate_snapshots.py
RUN python3 /tmp/generate_snapshots.py && rm /tmp/generate_snapshots.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y \
        python3 \
        python3-pip \
        binutils \
        xxd \
        gdb \
        gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY --from=builder /app/heapservice /app/heapservice
COPY --from=builder /app/snapshot_clean.bin /app/snapshot_clean.bin
COPY --from=builder /app/snapshot_attacked.bin /app/snapshot_attacked.bin
COPY heapservice_notes.c /app/heapservice_notes.c

WORKDIR /app
