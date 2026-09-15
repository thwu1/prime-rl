
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app
COPY app/spsc_queue.h /app/spsc_queue.h
COPY app/latency_sampler.h /app/latency_sampler.h
COPY app/main.cpp /app/main.cpp
COPY app/Makefile /app/Makefile

WORKDIR /app
