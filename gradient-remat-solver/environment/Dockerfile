FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/rematerialization

COPY starter/__init__.py /app/rematerialization/__init__.py
COPY starter/chain.py /app/rematerialization/chain.py
COPY starter/ops.py /app/rematerialization/ops.py
COPY starter/dp_core.c /app/rematerialization/dp_core.c
COPY starter/Makefile /app/rematerialization/Makefile

WORKDIR /app
