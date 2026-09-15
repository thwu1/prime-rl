FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip gcc make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/src

COPY app/src/blocked_attention.c /app/src/blocked_attention.c
COPY app/src/blocked_attention.h /app/src/blocked_attention.h
COPY app/Makefile /app/Makefile
COPY app/reference.py /app/reference.py
COPY app/attention.py /app/attention.py
COPY app/flash_attention.py /app/flash_attention.py

RUN grep -q "reference_causal_forward" /app/reference.py && \
    grep -q "reference_causal_backward" /app/reference.py
