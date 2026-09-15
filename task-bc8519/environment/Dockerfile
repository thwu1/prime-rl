
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY gpu_specs_init.sql /tmp/gpu_specs_init.sql
RUN sqlite3 /app/gpu_specs.db < /tmp/gpu_specs_init.sql && rm /tmp/gpu_specs_init.sql

COPY triton_matmul.py /app/triton_matmul.py
COPY gpu_arch_notes.md /app/gpu_arch_notes.md
COPY search_space.json /app/search_space.json
COPY workloads.json /app/workloads.json
COPY output_schema.json /app/output_schema.json

WORKDIR /app
