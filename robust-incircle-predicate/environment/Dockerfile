FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    cmake \
    python3-pip \
    libmpfr-dev \
    libgmp-dev \
    && rm -rf /var/lib/apt/lists/*


WORKDIR /app
COPY test_incircle.cpp /app/test_incircle.cpp
COPY incircle_naive.h /app/incircle_naive.h
