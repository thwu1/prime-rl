FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 && rm -rf /var/lib/apt/lists/*

COPY app/data/ /data/
COPY app/poop-src/ /app/poop-src/
COPY app/schema.json /app/schema.json
COPY app/db_schema.sql /app/db_schema.sql
COPY app/benchmark_compare.py /app/benchmark_compare.py

WORKDIR /app
