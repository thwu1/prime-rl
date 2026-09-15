FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    binutils \
    curl \
    strace \
    net-tools \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bin /app/exploits /app/analysis

COPY sanitize_direct.c /tmp/sanitize_direct.c
RUN gcc -O2 -o /app/bin/sanitize_direct /tmp/sanitize_direct.c && \
    strip -s /app/bin/sanitize_direct && \
    rm -f /tmp/sanitize_direct.c

COPY engine.py /app/engine.py
COPY server.py /app/server.py

WORKDIR /app
