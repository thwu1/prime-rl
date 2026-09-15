FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    cryptsetup-bin \
    python3-pip \
    e2fsprogs \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/sample && \
    dd if=/dev/urandom of=/app/sample/data.img bs=1M count=4 2>/dev/null

WORKDIR /app
