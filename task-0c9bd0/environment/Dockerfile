FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make iverilog && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY app/spec.md /app/spec.md
COPY app/fp8_api.h /app/fp8_api.h
COPY app/fp8.c /app/fp8.c
COPY app/Makefile /app/Makefile
COPY app/fp8_ctypes.py /app/fp8_ctypes.py
COPY app/fp8_adder.v /app/fp8_adder.v

WORKDIR /app
