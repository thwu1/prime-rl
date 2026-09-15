FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    jq \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/specs /app/data /app/lib /app/output

COPY rule_g33.txt /app/specs/rule_g33.txt
COPY trades.csv /app/data/trades.csv
COPY call_schedules.json /app/data/call_schedules.json
COPY vendor_report.csv /app/data/vendor_report.csv
COPY legacy_pricer.py /app/lib/legacy_pricer.py

