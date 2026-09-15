# Multi-stage build to prevent generation script from leaking into final image
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /app
COPY generate_flash.py /tmp/generate_flash.py
RUN python3 /tmp/generate_flash.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 python3-pip xxd openssl && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/flash_dump.bin /app/flash_dump.bin
COPY pm_static.yml /app/build_config/pm_static.yml
COPY mcuboot.conf /app/build_config/mcuboot.conf
WORKDIR /app
