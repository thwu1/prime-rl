FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    g++ \
    cmake \
    make \
    libboost-math-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY uniform_boundaries.h /app/uniform_boundaries.h
COPY test_runner.cpp /app/test_runner.cpp
COPY CMakeLists.txt /app/CMakeLists.txt
