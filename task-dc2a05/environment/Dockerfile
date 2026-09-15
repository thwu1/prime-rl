FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    g++ \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include /app/src /app/build

COPY qsbr.h /app/include/qsbr.h
COPY hash_util.h /app/include/hash_util.h
COPY concurrent_hashmap.h /app/include/concurrent_hashmap.h
COPY Makefile /app/Makefile

WORKDIR /app

