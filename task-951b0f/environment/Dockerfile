FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PYTHONPATH=/app


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY ir.py /app/ir.py
COPY executor.py /app/executor.py
COPY x86_defs.py /app/x86_defs.py
COPY graph.py /app/graph.py
COPY programs.py /app/programs.py
COPY allocator.py /app/allocator.py
COPY emitter.py /app/emitter.py
COPY runtime.c /app/runtime.c

WORKDIR /app
