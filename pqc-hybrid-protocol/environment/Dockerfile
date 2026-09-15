FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential cmake ninja-build git \
    libssl-dev python3-pip pkg-config jq \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch 0.15.0 https://github.com/open-quantum-safe/liboqs.git /app/liboqs

COPY broken_kem.c /app/broken_kem.c

RUN mkdir -p /app/output

WORKDIR /app
