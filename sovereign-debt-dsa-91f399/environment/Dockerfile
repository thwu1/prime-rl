FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


LABEL task.version="2"

RUN apt-get update && apt-get install -y python3 python3-pip sqlite3 gnuplot-nox && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/docs /app/output

COPY data/schema.sql /app/data/schema.sql
COPY data/config.toml /app/data/config.toml
COPY docs/methodology.md /app/docs/methodology.md

WORKDIR /app
