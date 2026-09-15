
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make sqlite3 libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src /app/docs /app/logs /app/output

COPY init_db.sql /tmp/init_db.sql
RUN sqlite3 /app/hardware.db < /tmp/init_db.sql && rm /tmp/init_db.sql

COPY qec_engine.c /app/src/qec_engine.c
COPY qec_engine.h /app/src/qec_engine.h
COPY src_Makefile /app/src/Makefile
COPY protocols.md /app/docs/protocols.md
COPY previous_run.log /app/logs/previous_run.log
COPY orchestrator.py /app/orchestrator.py

WORKDIR /app
