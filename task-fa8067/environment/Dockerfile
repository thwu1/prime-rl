FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    libc6-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY blockht.h /app/blockht.h
COPY blockht.c /app/blockht.c
COPY Makefile /app/Makefile

WORKDIR /app
