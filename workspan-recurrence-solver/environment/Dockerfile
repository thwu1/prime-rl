
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip sqlite3 make jq && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app

COPY schema.sql /app/schema.sql
COPY init_db.py /tmp/init_db.py
RUN python3 /tmp/init_db.py && rm /tmp/init_db.py /app/schema.sql

COPY Makefile.template /app/Makefile

WORKDIR /app
