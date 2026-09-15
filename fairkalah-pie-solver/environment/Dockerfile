
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make sqlite3 libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY src/ /app/src/
COPY Makefile /app/Makefile
COPY kalah.py /app/kalah.py
COPY positions.json /app/positions.json
COPY schema.sql /app/schema.sql

WORKDIR /app
