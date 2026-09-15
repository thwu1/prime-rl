FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    gcc \
    g++ \
    make \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY data/ /app/data/
COPY reference/ /app/reference/

