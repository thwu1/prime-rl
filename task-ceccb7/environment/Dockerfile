
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    sqlite3 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/tools
COPY crc_util.c /app/tools/crc_util.c
RUN gcc -o /app/tools/crc_util /app/tools/crc_util.c

COPY setup_db.py /tmp/setup_db.py
RUN python3 /tmp/setup_db.py && rm /tmp/setup_db.py
