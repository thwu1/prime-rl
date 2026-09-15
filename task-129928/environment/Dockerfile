
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/output

COPY setup/init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/data/clinical.db < /tmp/init_db.sql && \
    echo "Tables:" && sqlite3 /app/data/clinical.db ".tables" && \
    sqlite3 /app/data/clinical.db "SELECT COUNT(*) FROM site_parameters;" && \
    sqlite3 /app/data/clinical.db "SELECT COUNT(*) FROM psg_sessions;" && \
    rm /tmp/init_db.sql

COPY setup/qualifying_codes.sql /app/data/qualifying_codes.sql
COPY setup/model_output.jsonl /app/data/model_output.jsonl
COPY setup/cohort_summary.json /app/data/cohort_summary.json

COPY reference/ /app/reference/

WORKDIR /app
