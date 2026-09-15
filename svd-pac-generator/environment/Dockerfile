FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    cargo \
    rustc \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy task environment files (SVD with 4 peripherals including derived GPIOB)
COPY device.svd /app/device.svd
COPY reference.md /app/reference.md
COPY test_harness/ /app/test_harness/
