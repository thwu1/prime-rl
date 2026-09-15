FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    cmake \
    make \
    valgrind \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN rm -rf /app && mkdir -p /app

COPY app/poisson3d.c /app/poisson3d.c
COPY app/Makefile /app/Makefile

WORKDIR /app
