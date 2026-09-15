FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    cargo \
    python3-pip \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Pre-fetch crate dependencies to speed up compilation at solve time
COPY fetch_helper/ /tmp/fetch_helper/
RUN cd /tmp/fetch_helper && cargo fetch && rm -rf /tmp/fetch_helper

COPY workspace/ /app/

WORKDIR /app
