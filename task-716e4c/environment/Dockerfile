FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y gcc make python3-pip && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY walloc_original.c /app/walloc_original.c
COPY walloc_native.h /app/walloc_native.h

WORKDIR /app
