FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    python3-pip \
    pkg-config \
    libsuitesparse-dev \
    && rm -rf /var/lib/apt/lists/*

COPY matrices/ /app/matrices/
