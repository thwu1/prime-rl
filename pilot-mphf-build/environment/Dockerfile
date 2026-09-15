FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make libc6-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data

COPY mphf.h          /app/mphf.h
COPY Makefile         /app/Makefile
COPY naive_mphf.c     /app/naive_mphf.c
COPY generate_keys.py /app/generate_keys.py

RUN python3 /app/generate_keys.py

WORKDIR /app
