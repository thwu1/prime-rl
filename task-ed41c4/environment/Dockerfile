
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/intermediate /app/output

COPY data/patients_orgs.json /app/data/patients_orgs.json
COPY data/clinical.json /app/data/clinical.json
COPY table_schemas.sql /app/table_schemas.sql
COPY thresholds.json /app/thresholds.json
COPY schema.json /app/schema.json
COPY spec_notes.md /app/spec_notes.md

WORKDIR /app
