FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624


ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3-pip gcc make sqlite3 && \
    rm -rf /var/lib/apt/lists/*

COPY src/gmpb.c /app/src/gmpb.c
COPY src/gmpb.h /app/src/gmpb.h
COPY Makefile /app/Makefile
COPY init.sql /tmp/init.sql
COPY runner.py /app/runner.py
COPY optimizer.py /app/optimizer.py
COPY spec.md /app/spec.md

RUN sqlite3 /app/config.db < /tmp/init.sql && rm /tmp/init.sql

WORKDIR /app
