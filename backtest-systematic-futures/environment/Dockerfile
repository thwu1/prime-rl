FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip wget unzip && \
    rm -rf /var/lib/apt/lists/*

RUN wget -q https://github.com/duckdb/duckdb/releases/download/v1.1.3/duckdb_cli-linux-amd64.zip -O /tmp/duckdb.zip && \
    unzip -o /tmp/duckdb.zip -d /usr/local/bin && \
    rm /tmp/duckdb.zip && \
    chmod +x /usr/local/bin/duckdb

RUN mkdir -p /app/output

COPY data/SP500.csv data/EUROSTOXX.csv data/US10.csv data/GOLD.csv /tmp/data/
COPY config.yaml /app/config.yaml
COPY rules.toml /app/rules.toml
COPY init_db.sql /tmp/init_db.sql

RUN duckdb /app/market.duckdb < /tmp/init_db.sql && \
    rm -rf /tmp/data /tmp/init_db.sql

WORKDIR /app
