FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/collections/microban /app/collections/assorted /app/tools

COPY collections/microban/ /app/collections/microban/
COPY collections/assorted/ /app/collections/assorted/
COPY collections/benchlib.ssx /app/collections/benchlib.ssx

COPY tools/sokovalidate /app/tools/sokovalidate
RUN chmod +x /app/tools/sokovalidate

COPY setup_db.sql /tmp/setup_db.sql
RUN sqlite3 /app/benchmark.db < /tmp/setup_db.sql && rm /tmp/setup_db.sql

WORKDIR /app
