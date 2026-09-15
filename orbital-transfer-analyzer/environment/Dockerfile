FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y python3-pip sqlite3 jq make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/lib

COPY init.sql /app/init.sql
COPY config.toml /app/config.toml
COPY orbital.py /app/lib/orbital.py
COPY run_missions.py /app/run_missions.py
COPY Makefile /app/Makefile
COPY validate.jq /app/validate.jq
