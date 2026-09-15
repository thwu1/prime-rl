FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    cargo \
    rustc \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace
COPY app/ /app/

# Pre-fetch dependencies so the agent doesn't wait for downloads
WORKDIR /app
RUN cargo fetch
RUN cargo build -p smart_debug 2>&1 || true

WORKDIR /app
