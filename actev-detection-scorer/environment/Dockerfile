FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/output

COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/eval_data.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY detections.jsonl /app/detections.jsonl
COPY eval_config.toml /app/eval_config.toml
COPY protocol.md /app/protocol.md

WORKDIR /app
