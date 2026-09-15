FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y build-essential python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY spec.md /app/spec.md
COPY bf16.h /app/bf16.h
COPY bf16.c /app/bf16.c
COPY Makefile /app/Makefile
COPY bf16.py /app/bf16.py

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
