
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY scheduler.py /app/scheduler.py
COPY spec.md /app/spec.md
COPY schema.md /app/schema.md
COPY init_db.py /app/init_db.py

RUN python3 /app/init_db.py

WORKDIR /app
