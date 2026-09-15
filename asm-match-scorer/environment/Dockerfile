FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    binutils \
    && rm -rf /var/lib/apt/lists/*

COPY app/asm_sources/ /tmp/asm/

RUN mkdir -p /app/objects && for f in /tmp/asm/*.s; do as --64 -o "/app/objects/$(basename "$f" .s).o" "$f"; done && rm -rf /tmp/asm

WORKDIR /app
