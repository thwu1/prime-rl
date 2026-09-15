FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY topology.yaml /app/topology.yaml
COPY system_behavior.md /app/system_behavior.md
COPY init_db.sql /tmp/init_db.sql

RUN sqlite3 /app/incident.db < /tmp/init_db.sql && rm /tmp/init_db.sql

WORKDIR /app
