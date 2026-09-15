FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    libc6-dev \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/include /app/src

COPY brc.h /app/include/brc.h
COPY brc_stubs.c /app/src/brc.c
COPY Makefile /app/Makefile

WORKDIR /app
