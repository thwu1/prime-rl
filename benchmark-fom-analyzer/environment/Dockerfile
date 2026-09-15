FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    gawk \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/logs /app/tools

COPY data/spec.toml /app/spec.toml
COPY data/system.toml /app/system.toml
COPY data/schema.json /app/schema.json
COPY data/db_schema.sql /app/db_schema.sql
COPY data/tools/validate_milc.awk /app/tools/validate_milc.awk

COPY data/logs/lammps_spce_nano.log /app/logs/lammps_spce_nano.log
COPY data/logs/lammps_spce_tiny.log /app/logs/lammps_spce_tiny.log
COPY data/logs/milc_ref_32nodes.log /app/logs/milc_ref_32nodes.log
COPY data/logs/milc_ref_64nodes.log /app/logs/milc_ref_64nodes.log
COPY data/logs/milc_ref_128nodes.log /app/logs/milc_ref_128nodes.log
COPY data/logs/milc_ref_256nodes.log /app/logs/milc_ref_256nodes.log
COPY data/logs/workflow_9nodes.log /app/logs/workflow_9nodes.log

RUN chmod +x /app/tools/validate_milc.awk

WORKDIR /app
