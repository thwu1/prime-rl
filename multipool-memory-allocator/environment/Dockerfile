FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    python3-pip \
    meson \
    ninja-build \
    valgrind \
    binutils \
    && rm -rf /var/lib/apt/lists/*

COPY app_files/ /app/

WORKDIR /app

