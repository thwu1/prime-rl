FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 graphviz jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/bin /app/output

COPY init_db.sql /app/init_db.sql
RUN sqlite3 /app/monolith.db < /app/init_db.sql && rm /app/init_db.sql

COPY ratchet_policy.yaml /app/ratchet_policy.yaml
COPY output_schema.json /app/output_schema.json
COPY runtime_scan.csv /app/runtime_scan.csv
COPY depgraph /app/bin/depgraph
RUN chmod +x /app/bin/depgraph

ENV PATH="/app/bin:${PATH}"

WORKDIR /app
