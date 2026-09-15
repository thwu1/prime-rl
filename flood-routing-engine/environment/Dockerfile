FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY CMakeLists.txt /app/CMakeLists.txt
COPY src/ /app/src/
COPY data/ /app/data/

