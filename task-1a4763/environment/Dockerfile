FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    libc6-dev \
    make \
    jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/programs /app/tools

COPY app/ir.py /app/ir.py
COPY app/Makefile /app/Makefile
COPY app/programs/ /app/programs/
COPY app/tools/gen_stress_ir.c /app/tools/gen_stress_ir.c
COPY app/tools/check_alloc.py /app/tools/check_alloc.py

WORKDIR /app
