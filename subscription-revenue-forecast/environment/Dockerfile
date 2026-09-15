
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 jq wget unzip && \
    rm -rf /var/lib/apt/lists/*

RUN wget -qO /tmp/duckdb.zip "https://github.com/duckdb/duckdb/releases/download/v1.1.3/duckdb_cli-linux-amd64.zip" && \
    unzip -q /tmp/duckdb.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/duckdb && \
    rm /tmp/duckdb.zip

RUN mkdir -p /app/config /app/data /app/docs

COPY setup_db.sql /tmp/setup_db.sql
RUN sqlite3 /app/model.db < /tmp/setup_db.sql && rm /tmp/setup_db.sql

COPY create_parquet.sql /tmp/create_parquet.sql
RUN duckdb < /tmp/create_parquet.sql && rm /tmp/create_parquet.sql

COPY data/rate_curves.csv /app/data/rate_curves.csv
COPY data/hedge_book.csv /app/data/hedge_book.csv
COPY data/credit_provisions.csv /app/data/credit_provisions.csv
COPY data/seasonality_adjustments.csv /app/data/seasonality_adjustments.csv

COPY policy.toml /app/config/policy.toml
COPY output_schema.json /app/config/output_schema.json
COPY ifrs_framework.json /app/config/ifrs_framework.json
COPY cfo_memo.md /app/docs/cfo_memo.md

WORKDIR /app

# Test dependencies prebaked so the verifier runs offline
RUN pip3 install -q pytest==8.3.4
