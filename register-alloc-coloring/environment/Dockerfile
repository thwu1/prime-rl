FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3 python3-pip gcc && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY app/cfg.py /app/cfg.py
COPY app/allocator.py /app/allocator.py
COPY app/liveness.py /app/liveness.py
COPY app/interference.py /app/interference.py
COPY app/coloring.py /app/coloring.py
COPY app/codegen.py /app/codegen.py
COPY app/main.c /app/main.c
COPY app/test_local.py /app/test_local.py

WORKDIR /app
