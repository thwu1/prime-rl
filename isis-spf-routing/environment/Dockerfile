FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyang==2.6.0

RUN mkdir -p /app

COPY lsdb_seed.sql /app/lsdb_seed.sql
COPY isis-rib.yang /app/isis-rib.yang

RUN sqlite3 /app/isis_lsdb.db ".read /app/lsdb_seed.sql" && rm /app/lsdb_seed.sql

WORKDIR /app
