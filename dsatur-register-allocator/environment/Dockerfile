FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/regalloc /app

COPY app/ /opt/regalloc/
COPY app/register_allocator.py /app/register_allocator.py
COPY app/emit_asm.py /app/emit_asm.py

ENV PYTHONPATH=/app:/opt/regalloc
WORKDIR /app
