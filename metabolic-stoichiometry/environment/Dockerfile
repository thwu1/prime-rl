FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y python3-pip sqlite3 make && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/data /app/results

COPY data/metabolic_dump.sql /app/data/metabolic_dump.sql
COPY data/compound_reference.dat /app/data/compound_reference.dat
COPY data/config.json /app/data/config.json


WORKDIR /app
