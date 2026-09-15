
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 tshark && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY derp_protocol_spec.md /app/derp_protocol_spec.md
COPY output_schema.json /app/output_schema.json
COPY setup_db.sql /tmp/setup_db.sql
RUN sqlite3 /app/relay_metadata.db < /tmp/setup_db.sql && rm /tmp/setup_db.sql
