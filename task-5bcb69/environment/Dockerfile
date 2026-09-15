
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    gcc \
    make \
    libmpfr-dev \
    libgmp-dev \
    gdb \
    binutils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY app/cbrtf.c /app/cbrtf.c
COPY app/cbrtf.h /app/cbrtf.h
COPY app/spot_check.c /app/spot_check.c
COPY app/Makefile /app/Makefile

WORKDIR /app
