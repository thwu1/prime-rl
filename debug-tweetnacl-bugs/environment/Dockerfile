FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    gcc \
    make \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY tweetnacl.c /app/tweetnacl.c
COPY tweetnacl.h /app/tweetnacl.h
COPY randombytes.c /app/randombytes.c
COPY Makefile /app/Makefile
COPY SPEC.md /app/SPEC.md

WORKDIR /app
