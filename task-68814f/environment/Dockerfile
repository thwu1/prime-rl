FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && \
    apt-get install -y python3-pip sqlite3 xxd && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/engine

COPY engine_init.py /app/engine/__init__.py
COPY engine_storage.py /app/engine/storage.py
COPY engine_wal.py /app/engine/wal.py
COPY engine_config.py /app/engine/config.py
COPY engine_recovery.py /app/engine/recovery.py
COPY check_integrity.py /app/check_integrity.py
COPY simdb_ctl.py /usr/local/bin/simdb-ctl
RUN chmod +x /usr/local/bin/simdb-ctl

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py

WORKDIR /app
