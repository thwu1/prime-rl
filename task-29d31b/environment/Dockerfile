FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 python3-pip sqlite3 jq make \
    && rm -rf /var/lib/apt/lists/*

RUN rm -f /usr/lib/python3*/EXTERNALLY-MANAGED

RUN mkdir -p /app

COPY init.sql /tmp/init.sql
RUN sqlite3 /app/sokoban.db < /tmp/init.sql && rm /tmp/init.sql

COPY Makefile /app/Makefile
COPY report_schema.json /app/report_schema.json

WORKDIR /app
