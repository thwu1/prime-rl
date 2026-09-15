FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY undead_check.c /tmp/undead_check.c
RUN gcc -O2 -s -o /tmp/undead-check /tmp/undead_check.c

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    gcc \
    gdb \
    binutils \
    strace \
    xxd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/solutions

COPY setup_data.py /tmp/setup_data.py
RUN python3 /tmp/setup_data.py && rm /tmp/setup_data.py

COPY --from=builder /tmp/undead-check /app/undead-check
RUN chmod +x /app/undead-check

COPY undead_rules.c /app/src/undead_rules.c

WORKDIR /app
