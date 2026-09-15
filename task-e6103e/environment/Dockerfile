FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip python3-dev gcc make redis-server redis-tools && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY interface.py /app/interface.py
COPY sorted_set.py /app/sorted_set.py
COPY benchmark.py /app/benchmark.py
COPY node_ops.h /app/node_ops.h
COPY node_ops.c /app/node_ops.c
COPY Makefile /app/Makefile
COPY bulk_validate.lua /app/bulk_validate.lua

WORKDIR /app
