
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    nasm \
    gcc \
    g++ \
    make \
    python3 \
    python3-pip \
    xxd \
    binutils \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/binaries /tmp/asm_build

COPY prog_regops.asm prog_loops.asm prog_memory.asm prog_cond.asm \
     prog_rect.asm prog_bitstack.asm prog_penalty.asm /tmp/asm_build/

RUN cd /tmp/asm_build && \
    for f in *.asm; do nasm "$f" -o "/app/binaries/${f%.asm}.bin"; done && \
    rm -rf /tmp/asm_build

COPY 8086_timing.txt /app/

WORKDIR /app
