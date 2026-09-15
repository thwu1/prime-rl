FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/models /app/data

COPY comparison_loss.json /app/models/comparison_loss.json
COPY output_schema.json /app/output_schema.json
COPY setup_calibration_db.sql /tmp/setup_calibration_db.sql
RUN sqlite3 /app/calibration.db < /tmp/setup_calibration_db.sql && rm /tmp/setup_calibration_db.sql

WORKDIR /app
