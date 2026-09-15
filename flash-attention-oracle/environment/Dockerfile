FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/source

COPY source/setup.py /app/source/setup.py
COPY source/flash_attn_interface.py /app/source/flash_attn_interface.py
COPY source/benchmark_flash_attention.py /app/source/benchmark_flash_attention.py

COPY cluster_init.sql /tmp/cluster_init.sql
RUN sqlite3 /app/cluster.db < /tmp/cluster_init.sql && rm /tmp/cluster_init.sql

COPY cluster_config.toml /app/cluster_config.toml
COPY workloads.csv /app/workloads.csv

WORKDIR /app
