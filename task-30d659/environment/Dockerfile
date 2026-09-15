FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    binutils-riscv64-linux-gnu \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/input /app/reference

COPY input_basic.s /app/input/input_basic.s
COPY input_fusion.s /app/input/input_fusion.s
COPY input_mixed.s /app/input/input_mixed.s
COPY input_edge.s /app/input/input_edge.s
COPY reference_basic.s /app/reference/reference_basic.s
COPY reference_fusion.s /app/reference/reference_fusion.s

WORKDIR /app
