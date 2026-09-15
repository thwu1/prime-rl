FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY engine.cpp /app/engine.cpp
COPY CMakeLists.txt /app/CMakeLists.txt

WORKDIR /app
