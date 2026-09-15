FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624 AS builder
ENV PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update && apt-get install -y python3 && rm -rf /var/lib/apt/lists/*
COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py

FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/analytics.db /app/analytics.db
COPY --from=builder /app/expected.json /app/expected.json
COPY --from=builder /app/queries.sql /app/queries.sql
COPY --from=builder /app/audit_data.json /app/audit_data.json
COPY --from=builder /app/schema_spec.md /app/schema_spec.md
COPY --from=builder /app/discrepancy_notes.txt /app/discrepancy_notes.txt

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
