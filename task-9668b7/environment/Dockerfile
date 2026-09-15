FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-yaml \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY hls_cost.h /app/hls_cost.h
COPY hls_cost.c /app/hls_cost.c
RUN gcc -shared -fPIC -O2 -o /app/libhls_cost.so /app/hls_cost.c -lm

COPY dse_config.yaml /app/dse_config.yaml
COPY spec.md /app/spec.md
