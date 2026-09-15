FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624

ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && \
    apt-get install -y python3 python3-pip gcc make sqlite3 && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/src

COPY app/src/bank_model.c /app/src/bank_model.c
COPY app/src/Makefile /app/src/Makefile
COPY init_db.sql /tmp/init_db.sql

RUN sqlite3 /app/kernels.db < /tmp/init_db.sql && rm /tmp/init_db.sql

WORKDIR /app
