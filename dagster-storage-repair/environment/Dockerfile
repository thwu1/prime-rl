FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/pipeline

COPY setup_db.py /app/setup_db.py
COPY queries.py /app/queries.py
COPY reconciliation_buggy.py /app/pipeline/reconciliation.py
COPY pipeline_init.py /app/pipeline/__init__.py
COPY daemon_log.txt /app/daemon_log.txt
COPY architecture.md /app/ARCHITECTURE.md

RUN python3 /app/setup_db.py

WORKDIR /app
