
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY setup/generate_db.py /app/generate_db.py
COPY setup/queries.sql /app/queries.sql

RUN python3 /app/generate_db.py

WORKDIR /app
