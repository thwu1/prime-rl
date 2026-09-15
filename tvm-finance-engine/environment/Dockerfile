FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/native

COPY app/tvm.py /app/tvm.py
COPY app/test_quick.py /app/test_quick.py
COPY app/native/discount.c /app/native/discount.c
COPY app/native/Makefile /app/native/Makefile

WORKDIR /app
