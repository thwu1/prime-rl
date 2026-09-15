FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    build-essential \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY docs/ /app/docs/
COPY magma/storage.h /app/magma/storage.h
COPY magma/storage.c /app/magma/storage.c
COPY Makefile /app/Makefile

WORKDIR /app
