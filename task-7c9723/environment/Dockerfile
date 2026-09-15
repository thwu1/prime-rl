FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    graphviz \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app /app/viz

COPY chip_config.json /app/chip_config.json
COPY arch_spec.md /app/arch_spec.md
COPY output_schema.json /app/output_schema.json
COPY db_schema.sql /app/db_schema.sql

WORKDIR /app
